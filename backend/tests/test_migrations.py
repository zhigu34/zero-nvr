from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


EXPECTED_AUTH_TABLES = {
    "alembic_version",
    "users",
    "roles",
    "role_permissions",
    "user_roles",
    "user_sessions",
    "password_reset_tokens",
    "personal_api_tokens",
    "external_identities",
    "secret_records",
}


def test_alembic_upgrade_head_sqlite(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "migrations.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("ZERO_NVR_DATABASE_URL", database_url)

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert EXPECTED_AUTH_TABLES <= tables
    finally:
        engine.dispose()
