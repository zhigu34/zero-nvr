from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app import cli
from app.core.config import Settings
from app.core.db import (
    Base,
    Database,
    expected_schema_heads,
)
from app.core.security import SecretStore
from app.modules.backups.service import (
    BackupPolicyService,
)


CURRENT_KEY = "c" * 40
OLD_KEY = "o" * 40


def make_database(
    tmp_path: Path,
    *,
    environment: str = "production",
) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key=CURRENT_KEY,
        environment=environment,
        database_url=(
            f"sqlite:///{tmp_path / 'preflight.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_require_tmpfs=False,
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)

    revision = next(iter(expected_schema_heads()))
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS "
                "alembic_version ("
                "version_num VARCHAR(32) "
                "NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "DELETE FROM alembic_version"
            )
        )
        connection.execute(
            text(
                "INSERT INTO alembic_version "
                "(version_num) VALUES (:revision)"
            ),
            {"revision": revision},
        )
    return settings, database


def create_backup_policy(
    settings: Settings,
    database: Database,
) -> uuid.UUID:
    with database.session() as session:
        policy = BackupPolicyService(
            settings
        ).create(
            session,
            name="Pre-upgrade",
            enabled=True,
            repository=(
                "s3:s3.amazonaws.com/"
                "bucket/zero-nvr"
            ),
            password="restic-preflight-password",
            environment={
                "AWS_ACCESS_KEY_ID": "test-access",
                "AWS_SECRET_ACCESS_KEY": "test-secret",
            },
            initialize_if_missing=True,
            database_backend="sqlite",
            schedule={},
            retention={"keep_last": 3},
            verify_after_backup=True,
            repository_check_schedule={},
            include_deployment_config=True,
        )
        session.commit()
        return policy.id


def test_update_preflight_reports_database_keyring_and_backup(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path
    )
    try:
        policy_id = create_backup_policy(
            settings,
            database,
        )
        payload = cli._collect_update_preflight(
            settings,
            database,
            policy_selector=None,
        )
        assert payload["database"]["reachable"] is True
        assert payload["database"]["schema_current"] is True
        assert payload["database"]["backend"] == "sqlite"
        assert payload["database"]["size_bytes"] > 0

        assert payload["keyring"]["unreadable_records"] == 0
        assert payload["backup"] == {
            "required": True,
            "ready": True,
            "policy_id": str(policy_id),
            "policy_name": "Pre-upgrade",
        }
        assert "restic-preflight-password" not in repr(
            payload
        )
        assert "test-secret" not in repr(payload)
    finally:
        database.close()


def test_update_preflight_rejects_unreadable_keyring(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path,
        environment="test",
    )
    try:
        old_store = SecretStore(
            Settings(secret_key=OLD_KEY)
        )
        with database.session() as session:
            old_store.create_json(
                session,
                kind="legacy-test",
                owner_type="update-preflight",
                owner_id=uuid.uuid4(),
                value={"secret": "legacy"},
            )
            session.commit()

        with pytest.raises(
            RuntimeError,
            match="unreadable encrypted record",
        ):
            cli._collect_update_preflight(
                settings,
                database,
                policy_selector=None,
            )
    finally:
        database.close()
