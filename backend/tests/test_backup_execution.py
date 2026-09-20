from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select

import app.modules.backups.execution as execution_module
from app.core.config import Settings
from app.core.db import Base, Database
from app.integrations.restic import ResticBackupResult
from app.modules.backups.database_snapshot import DatabaseSnapshot
from app.modules.backups.execution import (
    BackupExecutionService,
    BackupRunService,
)
from app.modules.backups.models import BackupPolicy, BackupSet
from app.modules.backups.service import BackupPolicyService


def make_database(tmp_path: Path):
    settings = Settings(
        secret_key="backup-execution-test-secret-key-32-bytes",
        database_url=f"sqlite:///{tmp_path / 'backup.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def create_policy(
    settings: Settings,
    database: Database,
    *,
    verify: bool = False,
):
    with database.session() as session:
        policy = BackupPolicyService(settings).create(
            session,
            name="Nightly",
            enabled=True,
            repository="local:/backup",
            password="restic-password-value",
            environment={},
            initialize_if_missing=False,
            database_backend="sqlite",
            schedule={
                "cron": "0 3 * * *",
                "timezone": "UTC",
            },
            retention={"keep_last": 7},
            verify_after_backup=verify,
            repository_check_schedule={},
            include_deployment_config=False,
        )
        session.commit()
        return policy.id


class FakeSnapshotService:
    calls = 0

    def __init__(self, _settings) -> None:
        pass

    def snapshot(self, database, *, destination_dir):
        self.__class__.calls += 1
        destination_dir.mkdir(parents=True, exist_ok=True)
        path = destination_dir / "database.sqlite3"
        path.write_bytes(b"snapshot")
        return DatabaseSnapshot(
            path=path,
            engine="sqlite",
            size_bytes=len(b"snapshot"),
        )


class FakeRestic:
    backup_calls = 0
    latest: ResticBackupResult | None = None
    checked: list[str] = []
    forget_calls = 0

    def __init__(self, **_kwargs) -> None:
        pass

    def ensure_repository(self, *, initialize_if_missing):
        return None

    def latest_snapshot_for_tag(self, tag):
        assert tag.startswith("backup-set:")
        return self.__class__.latest

    def backup(self, *, paths, tags):
        self.__class__.backup_calls += 1
        assert any(path.name == "manifest.json" for path in paths)
        assert any(path.name == "database.sqlite3" for path in paths)
        assert "zero-nvr" in tags
        return ResticBackupResult(
            snapshot_id="a" * 64,
            size_bytes=123,
        )

    def verify_snapshot(self, snapshot_id):
        self.__class__.checked.append(snapshot_id)

    def check(self):
        return None

    def forget(self, retention):
        assert retention == {"keep_last": 7}
        self.__class__.forget_calls += 1


def reserve(
    settings: Settings,
    database: Database,
    policy_id,
    *,
    slot=None,
):
    with database.session() as session:
        policy = session.get(BackupPolicy, policy_id)
        assert policy is not None
        item, created = BackupRunService.reserve(
            session,
            policy=policy,
            settings=settings,
            database=database,
            reason="scheduled" if slot else "manual",
            schedule_slot=slot,
        )
        session.commit()
        return item.id, created


def test_schedule_slot_is_idempotent(tmp_path: Path) -> None:
    settings, database = make_database(tmp_path)
    try:
        policy_id = create_policy(settings, database)
        slot = "2026-09-20T03:00:00+00:00"

        first_id, created = reserve(
            settings,
            database,
            policy_id,
            slot=slot,
        )
        assert created is True

        second_id, created = reserve(
            settings,
            database,
            policy_id,
            slot=slot,
        )
        assert created is False
        assert second_id == first_id

        with database.session() as session:
            rows = list(
                session.scalars(
                    select(BackupSet).where(
                        BackupSet.backup_policy_id == policy_id
                    )
                )
            )
            assert len(rows) == 1
    finally:
        database.close()


def test_execution_creates_snapshot_and_completes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        policy_id = create_policy(
            settings,
            database,
            verify=True,
        )
        backup_id, _ = reserve(
            settings,
            database,
            policy_id,
        )

        FakeSnapshotService.calls = 0
        FakeRestic.backup_calls = 0
        FakeRestic.latest = None
        FakeRestic.checked = []
        FakeRestic.forget_calls = 0
        monkeypatch.setattr(
            execution_module,
            "DatabaseSnapshotService",
            FakeSnapshotService,
        )
        monkeypatch.setattr(
            execution_module,
            "ResticAdapter",
            FakeRestic,
        )

        state = BackupExecutionService(
            settings
        ).execute(
            database,
            backup_set_id=backup_id,
        )
        assert state == "COMPLETED"
        assert FakeSnapshotService.calls == 1
        assert FakeRestic.backup_calls == 1
        assert FakeRestic.checked == ["a" * 64]
        assert FakeRestic.forget_calls == 1

        with database.session() as session:
            item = session.get(BackupSet, backup_id)
            assert item is not None
            assert item.state == "COMPLETED"
            assert item.restic_snapshot_id == "a" * 64
            assert item.size_bytes == 123
            assert item.verification_state == "PASSED"
            assert item.error_code is None

        assert not (
            settings.cache_dir / "backups" / str(backup_id)
        ).exists()
    finally:
        database.close()


def test_worker_retry_reuses_existing_restic_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        policy_id = create_policy(settings, database)
        backup_id, _ = reserve(
            settings,
            database,
            policy_id,
        )

        FakeSnapshotService.calls = 0
        FakeRestic.backup_calls = 0
        FakeRestic.latest = ResticBackupResult(
            snapshot_id="b" * 64,
            size_bytes=None,
        )
        FakeRestic.checked = []
        FakeRestic.forget_calls = 0
        monkeypatch.setattr(
            execution_module,
            "DatabaseSnapshotService",
            FakeSnapshotService,
        )
        monkeypatch.setattr(
            execution_module,
            "ResticAdapter",
            FakeRestic,
        )

        state = BackupExecutionService(
            settings
        ).execute(
            database,
            backup_set_id=backup_id,
        )

        assert state == "COMPLETED"
        assert FakeRestic.backup_calls == 0
        with database.session() as session:
            item = session.get(BackupSet, backup_id)
            assert item is not None
            assert item.restic_snapshot_id == "b" * 64
    finally:
        database.close()
