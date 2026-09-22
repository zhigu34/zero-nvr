from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.auth.models import SecretRecord
from app.modules.backups.service import BackupPolicyService


REPOSITORY = "s3:s3.amazonaws.com/example-bucket/zero-nvr"
PASSWORD = "restic-super-secret-password"
ACCESS_KEY = "AKIA_TEST_SECRET_VALUE"


def make_database(tmp_path: Path):
    settings = Settings(
        secret_key="backup-policy-test-secret-key-32-bytes",
        database_url=f"sqlite:///{tmp_path / 'policy.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def test_backup_policy_secrets_are_encrypted_and_resolvable(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        service = BackupPolicyService(settings)
        with database.session() as session:
            policy = service.create(
                session,
                name="Nightly",
                enabled=True,
                repository=REPOSITORY,
                password=PASSWORD,
                environment={
                    "AWS_ACCESS_KEY_ID": ACCESS_KEY,
                },
                initialize_if_missing=True,
                database_backend="sqlite",
                schedule={
                    "cron": "0 3 * * *",
                    "timezone": "America/Los_Angeles",
                },
                retention={
                    "keep_last": 7,
                    "keep_daily": 14,
                },
                verify_after_backup=True,
                repository_check_schedule={},
                include_deployment_config=False,
            )
            session.commit()
            policy_id = policy.id

        with database.session() as session:
            policy = service.get(session, policy_id)
            resolved = service.resolve(
                session,
                policy=policy,
            )
            assert resolved.repository == REPOSITORY
            assert resolved.password == PASSWORD
            assert resolved.environment == {
                "AWS_ACCESS_KEY_ID": ACCESS_KEY,
            }
            assert resolved.initialize_if_missing is True

            secrets = list(
                session.scalars(
                    select(SecretRecord).where(
                        SecretRecord.owner_type
                        == "backup_policy",
                        SecretRecord.owner_id == policy_id,
                    )
                )
            )
            assert {
                item.kind for item in secrets
            } == {
                "backup_repository",
                "backup_credentials",
            }
            for item in secrets:
                payload = item.encrypted_payload
                assert REPOSITORY.encode() not in payload
                assert PASSWORD.encode() not in payload
                assert ACCESS_KEY.encode() not in payload
    finally:
        database.close()


def test_backup_policy_schedule_and_credential_update(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        service = BackupPolicyService(settings)
        with database.session() as session:
            policy = service.create(
                session,
                name="Nightly",
                enabled=True,
                repository="local:/backup",
                password=PASSWORD,
                environment={},
                initialize_if_missing=False,
                database_backend="sqlite",
                schedule={},
                retention={},
                verify_after_backup=True,
                repository_check_schedule={},
                include_deployment_config=False,
            )
            session.commit()
            policy_id = policy.id

        with database.session() as session:
            policy = service.get(session, policy_id)
            policy = service.update(
                session,
                policy=policy,
                changes={
                    "schedule": {
                        "cron": "*/15 * * * *",
                        "timezone": "UTC",
                    },
                    "credentials_action": "replace",
                    "credentials": {
                        "password": "new-restic-password-value",
                        "environment": {
                            "B2_ACCOUNT_ID": "account-id",
                        },
                    },
                },
            )
            session.commit()

        with database.session() as session:
            policy = service.get(session, policy_id)
            resolved = service.resolve(
                session,
                policy=policy,
            )
            assert policy.schedule_json == {
                "cron": "*/15 * * * *",
                "timezone": "UTC",
            }
            assert (
                resolved.password
                == "new-restic-password-value"
            )
            assert resolved.environment == {
                "B2_ACCOUNT_ID": "account-id",
            }
    finally:
        database.close()
