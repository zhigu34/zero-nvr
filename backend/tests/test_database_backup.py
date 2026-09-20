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



def test_local_safety_snapshot_restore_is_atomic_and_keeps_rollback_copy(
    tmp_path: Path,
) -> None:
    from app.cli import (
        _restore_safety_snapshot,
        _validated_safety_snapshot,
    )

    settings = Settings(
        secret_key="sqlite-rollback-test-secret-key-32-bytes",
        database_url=f"sqlite:///{tmp_path / 'active.db'}",
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
                    namespace="rollback-test",
                    value_json={"value": "before"},
                )
            )
            session.commit()

        snapshot = DatabaseSnapshotService(
            settings
        ).snapshot(
            database,
            destination_dir=(
                settings.data_dir
                / "safety-backups"
                / "pre-upgrade"
            ),
        )

        with database.session() as session:
            setting = session.get(
                SystemSetting,
                "rollback-test",
            )
            assert setting is not None
            setting.value_json = {
                "value": "after"
            }
            session.commit()

        validated = _validated_safety_snapshot(
            settings=settings,
            database=database,
            raw_path=str(snapshot.path),
        )
        backend, rollback_copy = (
            _restore_safety_snapshot(
                settings=settings,
                database=database,
                snapshot=validated,
            )
        )
        assert backend == "sqlite"
        assert rollback_copy is not None
        assert rollback_copy.is_file()

        restored = sqlite3.connect(
            str(Path(database.url.database))
        )
        rollback = sqlite3.connect(
            str(rollback_copy)
        )
        try:
            restored_value = restored.execute(
                "SELECT value_json FROM system_settings "
                "WHERE namespace = ?",
                ("rollback-test",),
            ).fetchone()
            rollback_value = rollback.execute(
                "SELECT value_json FROM system_settings "
                "WHERE namespace = ?",
                ("rollback-test",),
            ).fetchone()
        finally:
            restored.close()
            rollback.close()

        assert restored_value is not None
        assert "before" in restored_value[0]
        assert rollback_value is not None
        assert "after" in rollback_value[0]
    finally:
        database.close()


def test_safety_snapshot_restore_rejects_path_outside_data_safety_dir(
    tmp_path: Path,
) -> None:
    import pytest

    from app.cli import _validated_safety_snapshot

    settings = Settings(
        secret_key="sqlite-rollback-path-test-secret-key-32-bytes",
        database_url=f"sqlite:///{tmp_path / 'active.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    outside = tmp_path / "database.sqlite3"
    outside.write_bytes(b"not-a-safety-snapshot")

    try:
        with pytest.raises(
            RuntimeError,
            match="safety-backups",
        ):
            _validated_safety_snapshot(
                settings=settings,
                database=database,
                raw_path=str(outside),
            )
    finally:
        database.close()
