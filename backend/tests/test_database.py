from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import Database


def make_database(tmp_path: Path) -> Database:
    settings = Settings(
        secret_key="x" * 32,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        database_url=f"sqlite:///{tmp_path / 'zero-nvr.db'}",
        sqlite_busy_timeout_ms=4321,
        sqlite_synchronous="NORMAL",
    )
    database = Database(settings)
    database.initialize_runtime()
    return database


def test_sqlite_runtime_pragmas(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    try:
        with database.engine.connect() as connection:
            journal_mode = connection.exec_driver_sql(
                "PRAGMA journal_mode"
            ).scalar_one()
            synchronous = connection.exec_driver_sql(
                "PRAGMA synchronous"
            ).scalar_one()
            foreign_keys = connection.exec_driver_sql(
                "PRAGMA foreign_keys"
            ).scalar_one()
            busy_timeout = connection.exec_driver_sql(
                "PRAGMA busy_timeout"
            ).scalar_one()

        assert str(journal_mode).lower() == "wal"
        assert synchronous == 1  # SQLite NORMAL
        assert foreign_keys == 1
        assert busy_timeout == 4321
    finally:
        database.close()


def test_database_ping(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    try:
        database.ping()
    finally:
        database.close()
