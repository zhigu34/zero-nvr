from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.core.db.transfer import (
    DatabaseTransferError,
    DatabaseTransferService,
)
from app.modules.auth.models import Role, User
from app.modules.system.models import SystemSetting


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(root / "alembic"),
    )
    return config


def _upgrade(url: str) -> None:
    previous = os.environ.get(
        "ZERO_NVR_DATABASE_URL"
    )
    os.environ["ZERO_NVR_DATABASE_URL"] = url
    try:
        command.upgrade(
            _alembic_config(),
            "head",
        )
    finally:
        if previous is None:
            os.environ.pop(
                "ZERO_NVR_DATABASE_URL",
                None,
            )
        else:
            os.environ[
                "ZERO_NVR_DATABASE_URL"
            ] = previous


def _database(
    tmp_path: Path,
    url: str,
) -> Database:
    settings = Settings(
        secret_key="transfer-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=url,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    return database


def _seed(source: Database) -> tuple[str, str]:
    created_at = datetime(
        2026,
        9,
        20,
        12,
        34,
        56,
        tzinfo=UTC,
    )
    with source.session() as session:
        role = Role(
            name="Transferred Viewer",
            description="portable role",
            built_in=False,
            created_at=created_at,
            updated_at=created_at,
        )
        user = User(
            username="portable-user",
            display_name="Portable User",
            email="portable@example.test",
            password_hash=None,
            enabled=True,
            created_at=created_at,
            updated_at=created_at,
        )
        user.roles = [role]
        session.add_all(
            [
                role,
                user,
                SystemSetting(
                    namespace="transfer.test",
                    value_json={
                        "nested": {
                            "enabled": True,
                            "count": 3,
                        },
                        "items": ["a", "b"],
                    },
                ),
            ]
        )
        session.commit()
        return str(user.id), str(role.id)


def test_database_transfer_preserves_ids_json_and_relationships(
    tmp_path: Path,
) -> None:
    source_url = (
        f"sqlite:///{tmp_path / 'source.db'}"
    )
    target_url = (
        f"sqlite:///{tmp_path / 'target.db'}"
    )
    _upgrade(source_url)
    _upgrade(target_url)

    source = _database(
        tmp_path,
        source_url,
    )
    target = _database(
        tmp_path,
        target_url,
    )
    try:
        user_id, role_id = _seed(source)
        result = DatabaseTransferService(
            batch_size=2
        ).transfer(
            source=source,
            target=target,
        )

        assert result.total_rows >= 4
        assert result.table_counts["users"] == 1
        assert result.table_counts["roles"] == 1
        assert result.table_counts["user_roles"] == 1

        with target.session() as session:
            user = session.scalar(
                select(User).where(
                    User.username
                    == "portable-user"
                )
            )
            assert user is not None
            assert str(user.id) == user_id
            assert len(user.roles) == 1
            assert str(user.roles[0].id) == role_id
            assert user.created_at == datetime(
                2026,
                9,
                20,
                12,
                34,
                56,
                tzinfo=UTC,
            )

            setting = session.get(
                SystemSetting,
                "transfer.test",
            )
            assert setting is not None
            assert setting.value_json[
                "nested"
            ] == {
                "enabled": True,
                "count": 3,
            }
    finally:
        source.close()
        target.close()


def test_database_transfer_refuses_nonempty_target(
    tmp_path: Path,
) -> None:
    source_url = (
        f"sqlite:///{tmp_path / 'source-nonempty.db'}"
    )
    target_url = (
        f"sqlite:///{tmp_path / 'target-nonempty.db'}"
    )
    _upgrade(source_url)
    _upgrade(target_url)

    source = _database(
        tmp_path,
        source_url,
    )
    target = _database(
        tmp_path,
        target_url,
    )
    try:
        _seed(source)
        _seed(target)
        with pytest.raises(
            DatabaseTransferError
        ) as exc_info:
            DatabaseTransferService().transfer(
                source=source,
                target=target,
            )
        assert (
            exc_info.value.code
            == "database_transfer_target_not_empty"
        )
    finally:
        source.close()
        target.close()


@pytest.mark.skipif(
    not os.getenv("ZERO_NVR_TEST_POSTGRES_URL"),
    reason="PostgreSQL CI service is unavailable",
)
def test_database_transfer_sqlite_to_postgresql(
    tmp_path: Path,
) -> None:
    source_url = (
        f"sqlite:///{tmp_path / 'source-postgres.db'}"
    )
    target_url = os.environ[
        "ZERO_NVR_TEST_POSTGRES_URL"
    ]
    _upgrade(source_url)
    _upgrade(target_url)

    source = _database(
        tmp_path,
        source_url,
    )
    target = _database(
        tmp_path,
        target_url,
    )
    try:
        user_id, role_id = _seed(source)
        result = DatabaseTransferService().transfer(
            source=source,
            target=target,
        )
        assert result.source_backend == "sqlite"
        assert result.target_backend == "postgresql"

        with target.session() as session:
            user = session.scalar(
                select(User).where(
                    User.username
                    == "portable-user"
                )
            )
            assert user is not None
            assert str(user.id) == user_id
            assert str(user.roles[0].id) == role_id
    finally:
        source.close()
        target.close()
