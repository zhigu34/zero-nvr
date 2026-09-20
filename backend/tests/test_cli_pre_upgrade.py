from __future__ import annotations

import argparse
import uuid
from pathlib import Path

import pytest

import app.cli as cli_module
from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.backups.models import (
    BackupPolicy,
    BackupSet,
)
from app.modules.backups.service import (
    BackupPolicyService,
)


def make_database(
    tmp_path: Path,
) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key=(
            "pre-upgrade-backup-test-secret-key-"
            "32-bytes-minimum"
        ),
        database_url=(
            f"sqlite:///{tmp_path / 'backup.db'}"
        ),
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
    name: str,
    verify: bool,
) -> uuid.UUID:
    with database.session() as session:
        policy = BackupPolicyService(
            settings
        ).create(
            session,
            name=name,
            enabled=True,
            repository="local:/backup",
            password="restic-password-value",
            environment={},
            initialize_if_missing=False,
            database_backend="sqlite",
            schedule={},
            retention={},
            verify_after_backup=verify,
            repository_check_schedule={},
            include_deployment_config=False,
        )
        session.commit()
        return policy.id


def test_pre_upgrade_policy_requires_unique_verified_policy(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        unverified = create_policy(
            settings,
            database,
            name="Unverified",
            verify=False,
        )
        with pytest.raises(RuntimeError):
            cli_module._pre_upgrade_policy(
                database,
                None,
            )

        with pytest.raises(RuntimeError):
            cli_module._pre_upgrade_policy(
                database,
                str(unverified),
            )

        first = create_policy(
            settings,
            database,
            name="Primary",
            verify=True,
        )
        selected = cli_module._pre_upgrade_policy(
            database,
            None,
        )
        assert selected.id == first

        second = create_policy(
            settings,
            database,
            name="Secondary",
            verify=True,
        )
        with pytest.raises(RuntimeError):
            cli_module._pre_upgrade_policy(
                database,
                None,
            )

        chosen = cli_module._pre_upgrade_policy(
            database,
            str(second),
        )
        assert chosen.id == second
    finally:
        database.close()


def test_pre_upgrade_command_requires_passed_verification(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    settings, database = make_database(tmp_path)
    policy_id = create_policy(
        settings,
        database,
        name="Primary",
        verify=True,
    )

    monkeypatch.setattr(
        cli_module,
        "_settings_database",
        lambda: (settings, database),
    )

    def fake_execute(
        self,
        database_arg,
        *,
        backup_set_id,
    ) -> str:
        assert database_arg is database
        with database.session() as session:
            item = session.get(
                BackupSet,
                backup_set_id,
            )
            assert item is not None
            item.state = "COMPLETED"
            item.verification_state = "PASSED"
            item.restic_snapshot_id = "a" * 64
            session.commit()
        return "COMPLETED"

    monkeypatch.setattr(
        cli_module.BackupExecutionService,
        "execute",
        fake_execute,
    )

    result = cli_module.pre_upgrade_backup_command(
        argparse.Namespace(
            policy=str(policy_id)
        )
    )
    assert result == 0
    output = capsys.readouterr().out
    assert '"verification_state": "PASSED"' in output
    assert '"restic_snapshot_id": "' in output


def test_pre_upgrade_command_rejects_failed_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, database = make_database(tmp_path)
    policy_id = create_policy(
        settings,
        database,
        name="Primary",
        verify=True,
    )

    monkeypatch.setattr(
        cli_module,
        "_settings_database",
        lambda: (settings, database),
    )

    def fake_execute(
        self,
        database_arg,
        *,
        backup_set_id,
    ) -> str:
        with database.session() as session:
            item = session.get(
                BackupSet,
                backup_set_id,
            )
            assert item is not None
            item.state = "COMPLETED"
            item.verification_state = "FAILED"
            item.restic_snapshot_id = "b" * 64
            session.commit()
        return "COMPLETED"

    monkeypatch.setattr(
        cli_module.BackupExecutionService,
        "execute",
        fake_execute,
    )

    with pytest.raises(
        RuntimeError,
        match="verified restic snapshot",
    ):
        cli_module.pre_upgrade_backup_command(
            argparse.Namespace(
                policy=str(policy_id)
            )
        )
