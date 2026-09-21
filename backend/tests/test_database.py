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
            wal_autocheckpoint = (
                connection.exec_driver_sql(
                    "PRAGMA wal_autocheckpoint"
                ).scalar_one()
            )

        assert str(journal_mode).lower() == "wal"
        assert synchronous == 1  # SQLite NORMAL
        assert foreign_keys == 1
        assert busy_timeout == 4321
        assert wal_autocheckpoint == 1000
    finally:
        database.close()


def test_sqlite_runtime_health_reports_checkpoint_state(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    try:
        health = database.sqlite_runtime_health()
        assert health is not None
        assert health.journal_mode == "wal"
        assert health.busy_timeout_ms == 4321
        assert health.wal_autocheckpoint_pages == 1000
        assert health.page_size_bytes > 0
        assert health.wal_pages >= 0
        assert health.checkpointed_pages >= 0
        assert health.backlog_pages >= 0
        assert health.wal_bytes >= 0
        assert health.write_pressure == "normal"
    finally:
        database.close()


def test_sqlite_write_pressure_thresholds() -> None:
    threshold = Database.sqlite_wal_autocheckpoint_pages
    assert (
        Database._sqlite_write_pressure(
            wal_pages=threshold * 3,
            backlog_pages=threshold - 1,
            checkpoint_busy=False,
        )
        == "normal"
    )
    assert (
        Database._sqlite_write_pressure(
            wal_pages=threshold * 4,
            backlog_pages=0,
            checkpoint_busy=False,
        )
        == "elevated"
    )
    assert (
        Database._sqlite_write_pressure(
            wal_pages=0,
            backlog_pages=threshold * 2,
            checkpoint_busy=False,
        )
        == "high"
    )
    assert (
        Database._sqlite_write_pressure(
            wal_pages=0,
            backlog_pages=0,
            checkpoint_busy=True,
        )
        == "high"
    )


def test_database_ping(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    try:
        database.ping()
    finally:
        database.close()
