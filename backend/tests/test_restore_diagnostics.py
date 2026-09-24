from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app import cli
from app.core.config import Settings
from app.core.db import Base, Database
from app.core.security import SecretStore
from app.modules.audit.models import AuditEvent


OLD_KEY = "o" * 40
NEW_KEY = "n" * 40


def build_staged_backup(
    tmp_path: Path,
    *,
    include_key_metadata: bool,
) -> tuple[Path, str]:
    root = tmp_path / "staging"
    root.mkdir()
    snapshot = root / "database.sqlite3"
    settings = Settings(
        secret_key=OLD_KEY,
        database_url=f"sqlite:///{snapshot}",
        data_dir=tmp_path / "source-data",
        cache_dir=tmp_path / "source-cache",
        prebuffer_require_tmpfs=False,
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    try:
        store = SecretStore(settings)
        with database.session() as session:
            store.create(
                session,
                kind="restore_test",
                owner_type="restore_test",
                owner_id=uuid.uuid4(),
                plaintext=b"recoverable-secret",
            )
            required = sorted(
                store.record_key_ids(session)
            )
            session.commit()
    finally:
        database.close()

    manifest = {
        "backup_set_id": str(uuid.uuid4()),
        "policy_id": str(uuid.uuid4()),
        "created_at": "2026-09-24T00:00:00+00:00",
        "app_version": "0.1.0",
        "schema_revision": "unknown",
        "database_engine": "sqlite",
        "database_snapshot": snapshot.name,
        "recordings_included": False,
        "recovery_kit_required": True,
    }
    if include_key_metadata:
        manifest["secret_store_key_ids"] = required
    (root / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return root, required[0]


def deployment(
    tmp_path: Path,
    *,
    previous: bool,
) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key=NEW_KEY,
        secret_key_previous=(
            [OLD_KEY] if previous else []
        ),
        database_url=(
            f"sqlite:///{tmp_path / 'target.db'}"
        ),
        data_dir=tmp_path / "target-data",
        cache_dir=tmp_path / "target-cache",
        prebuffer_require_tmpfs=False,
    )
    return settings, Database(settings)


def test_restore_manifest_rejects_missing_keyring(
    tmp_path: Path,
) -> None:
    root, required_key = build_staged_backup(
        tmp_path,
        include_key_metadata=True,
    )
    settings, database = deployment(
        tmp_path,
        previous=False,
    )
    try:
        with pytest.raises(
            RuntimeError,
            match="secret_keyring_mismatch",
        ) as exc:
            cli._validate_restore_manifest(
                settings=settings,
                database=database,
                root=root,
            )
        assert required_key in str(exc.value)
    finally:
        database.close()


def test_legacy_sqlite_restore_detects_wrong_keyring(
    tmp_path: Path,
) -> None:
    root, _required_key = build_staged_backup(
        tmp_path,
        include_key_metadata=False,
    )
    settings, database = deployment(
        tmp_path,
        previous=False,
    )
    try:
        with pytest.raises(
            RuntimeError,
            match=(
                "secret_keyring_mismatch|"
                "secret_keyring_unreadable"
            ),
        ):
            cli._validate_restore_manifest(
                settings=settings,
                database=database,
                root=root,
            )
    finally:
        database.close()


def test_restore_accepts_matching_previous_key(
    tmp_path: Path,
) -> None:
    root, _required_key = build_staged_backup(
        tmp_path,
        include_key_metadata=True,
    )
    settings, database = deployment(
        tmp_path,
        previous=True,
    )
    try:
        _manifest_path, manifest, snapshot = (
            cli._validate_restore_manifest(
                settings=settings,
                database=database,
                root=root,
            )
        )
        assert manifest["database_engine"] == "sqlite"
        assert snapshot.name == "database.sqlite3"
    finally:
        database.close()



def test_host_restore_audit_uses_system_actor(
    tmp_path: Path,
) -> None:
    settings, database = deployment(
        tmp_path,
        previous=True,
    )
    Base.metadata.create_all(database.engine)
    database.close()

    backup_set_id = uuid.uuid4()
    assert cli._record_host_restore_audit(
        settings=settings,
        manifest={
            "backup_set_id": str(
                backup_set_id
            )
        },
        backend="sqlite",
    ) is True

    restored = Database(settings)
    try:
        with restored.session() as session:
            event = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action
                    == "backup.restore"
                )
            )
        assert event is not None
        assert event.actor_type == "system"
        assert event.actor_id is None
        assert event.resource_type == "backup_set"
        assert event.resource_id == backup_set_id
        assert event.metadata_json == {
            "source": "deploy.sh",
            "database_engine": "sqlite",
            "recordings_modified": False,
        }
    finally:
        restored.close()
