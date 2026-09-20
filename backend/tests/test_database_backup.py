from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.backups.database_snapshot import (
    DatabaseSnapshotService,
)
from app.modules.system.models import SystemSetting


def test_sqlite_online_backup_is_consistent_and_independent(
    tmp_path: Path,
) -> None:
    settings = Settings(
        secret_key="sqlite-backup-test-secret-key-32-bytes",
        database_url=f"sqlite:///{tmp_path / 'source.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)

    try:
        with database.session() as session:
            session.add(
                SystemSetting(
                    namespace="backup-test",
                    value_json={"value": 42},
                )
            )
            session.commit()

        result = DatabaseSnapshotService(
            settings
        ).snapshot(
            database,
            destination_dir=tmp_path / "snapshot",
        )

        assert result.engine == "sqlite"
        assert result.size_bytes > 0
        assert result.path.is_file()
        assert result.path != Path(
            database.url.database
        ).resolve()

        snapshot = sqlite3.connect(
            str(result.path)
        )
        try:
            row = snapshot.execute(
                "SELECT value_json FROM system_settings "
                "WHERE namespace = ?",
                ("backup-test",),
            ).fetchone()
            integrity = snapshot.execute(
                "PRAGMA integrity_check"
            ).fetchone()
        finally:
            snapshot.close()

        assert row is not None
        assert "42" in row[0]
        assert integrity == ("ok",)
    finally:
        database.close()
