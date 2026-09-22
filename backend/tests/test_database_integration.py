from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.db import Database
from app.modules.auth.service import AuthService


ADMIN_PASSWORD = "correct-horse-battery-staple"


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(root / "alembic"),
    )
    return config


def _upgrade(database_url: str) -> None:
    previous = os.environ.get("ZERO_NVR_DATABASE_URL")
    os.environ["ZERO_NVR_DATABASE_URL"] = database_url
    try:
        command.upgrade(_alembic_config(), "head")
    finally:
        if previous is None:
            os.environ.pop("ZERO_NVR_DATABASE_URL", None)
        else:
            os.environ["ZERO_NVR_DATABASE_URL"] = previous


@contextmanager
def _temporary_postgresql_database(
    base_url: str,
) -> Iterator[str]:
    base = make_url(base_url)
    if base.drivername in {"postgresql", "postgres"}:
        base = base.set(drivername="postgresql+psycopg")

    database_name = f"zero_nvr_it_{uuid.uuid4().hex[:24]}"
    admin_url = base.set(database="postgres")
    target_url = base.set(database=database_name)
    admin = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )

    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(
                f'CREATE DATABASE "{database_name}"'
            )
        yield target_url.render_as_string(
            hide_password=False
        )
    finally:
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name "
                    "AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}"'
            )
        admin.dispose()


def _exercise_auth_product_flow(
    tmp_path: Path,
    *,
    database_url: str,
    expected_backend: str,
) -> None:
    _upgrade(database_url)
    settings = Settings(
        secret_key="database-integration-secret-key-32-bytes",
        environment="test",
        database_url=database_url,
        data_dir=tmp_path / expected_backend / "data",
        cache_dir=tmp_path / expected_backend / "cache",
        session_cookie_secure=False,
    )
    database = Database(settings)
    database.initialize_runtime()
    auth = AuthService(settings)

    try:
        assert (
            database.url.get_backend_name()
            == expected_backend
        )

        with database.session() as session:
            user = auth.create_initial_administrator(
                session,
                username="integration-admin",
                display_name="Integration Admin",
                email="integration@example.test",
                password=ADMIN_PASSWORD,
            )
            user_id = user.id
            session.commit()

        with database.session() as session:
            authenticated = auth.authenticate(
                session,
                username="integration-admin",
                password=ADMIN_PASSWORD,
            )
            assert authenticated.id == user_id
            user_session, token = auth.create_session(
                session,
                authenticated,
                client_info={"source": "database-integration"},
            )
            session_id = user_session.id
            session.commit()

        with database.session() as session:
            context = auth.resolve_session(
                session,
                token,
            )
            assert context.user.id == user_id
            assert context.session is not None
            assert context.session.id == session_id
            assert "Administrator" in context.roles
            assert context.permissions
    finally:
        database.close()


def test_sqlite_production_integration_harness(
    tmp_path: Path,
) -> None:
    _exercise_auth_product_flow(
        tmp_path,
        database_url=(
            f"sqlite:///{tmp_path / 'production.sqlite3'}"
        ),
        expected_backend="sqlite",
    )


@pytest.mark.skipif(
    not os.getenv("ZERO_NVR_TEST_POSTGRES_URL"),
    reason="PostgreSQL CI service is unavailable",
)
def test_postgresql_production_integration_harness(
    tmp_path: Path,
) -> None:
    with _temporary_postgresql_database(
        os.environ["ZERO_NVR_TEST_POSTGRES_URL"]
    ) as database_url:
        _exercise_auth_product_flow(
            tmp_path,
            database_url=database_url,
            expected_backend="postgresql",
        )
