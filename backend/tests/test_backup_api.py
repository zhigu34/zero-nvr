from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.backups.models import BackupSet
from app.modules.backups.service import BackupPolicyService


PASSWORD = "correct-horse-battery-staple"
RESTIC_PASSWORD = "restic-api-secret-password"
AWS_SECRET = "aws-secret-access-value"


class FakeBackupTasks:
    def __init__(self) -> None:
        self.runs: list[uuid.UUID] = []
        self.verifies: list[uuid.UUID] = []

    def run(self, backup_set_id: uuid.UUID) -> None:
        self.runs.append(backup_set_id)

    def verify(self, backup_set_id: uuid.UUID) -> None:
        self.verifies.append(backup_set_id)


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="backup-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'backup-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    app.state.backup_tasks = FakeBackupTasks()
    return app


def setup_admin(client: TestClient) -> None:
    created = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": PASSWORD,
        },
    )
    assert created.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": PASSWORD},
    )
    assert login.status_code == 200


def policy_payload() -> dict[str, object]:
    return {
        "name": "Nightly",
        "enabled": True,
        "repository": "s3:s3.amazonaws.com/bucket/zero-nvr",
        "credentials": {
            "password": RESTIC_PASSWORD,
            "environment": {
                "AWS_SECRET_ACCESS_KEY": AWS_SECRET,
            },
        },
        "initialize_if_missing": True,
        "database_backend": "sqlite",
        "schedule": {
            "cron": "0 3 * * *",
            "timezone": "UTC",
        },
        "retention": {"keep_last": 7},
        "verify_after_backup": True,
        "repository_check_schedule": {},
        "include_deployment_config": False,
    }


def test_backup_policy_api_redacts_secrets_updates_and_queues_run(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        created = client.post(
            "/api/v1/backups/policies",
            json=policy_payload(),
        )
        assert created.status_code == 201
        body = created.json()
        policy_id = uuid.UUID(body["id"])
        serialized = str(body)
        assert RESTIC_PASSWORD not in serialized
        assert AWS_SECRET not in serialized
        assert "repository" not in body
        assert body["repository_configured"] is True
        assert body["credentials_configured"] is True

        updated = client.patch(
            f"/api/v1/backups/policies/{policy_id}",
            json={
                "credentials_action": "replace",
                "credentials": {
                    "password": "new-restic-secret-password",
                    "environment": {
                        "B2_ACCOUNT_KEY": "new-b2-secret",
                    },
                },
                "retention": {
                    "keep_last": 5,
                    "keep_daily": 7,
                },
            },
        )
        assert updated.status_code == 200

        with app.state.database.session() as session:
            policy = BackupPolicyService.get(
                session,
                policy_id,
            )
            resolved = BackupPolicyService(
                app.state.settings
            ).resolve(
                session,
                policy=policy,
            )
            assert (
                resolved.password
                == "new-restic-secret-password"
            )
            assert resolved.environment == {
                "B2_ACCOUNT_KEY": "new-b2-secret",
            }

        password_only = client.patch(
            f"/api/v1/backups/policies/{policy_id}",
            json={
                "credentials_action": "replace",
                "credentials": {
                    "password": "rotated-restic-password",
                }
            },
        )
        assert password_only.status_code == 200

        with app.state.database.session() as session:
            policy = BackupPolicyService.get(
                session,
                policy_id,
            )
            resolved = BackupPolicyService(
                app.state.settings
            ).resolve(
                session,
                policy=policy,
            )
            assert resolved.password == "rotated-restic-password"
            assert resolved.environment == {
                "B2_ACCOUNT_KEY": "new-b2-secret",
            }

        run = client.post(
            "/api/v1/backups/run",
            json={
                "policy_id": str(policy_id),
                "reason": "manual",
            },
        )
        assert run.status_code == 202
        backup_id = uuid.UUID(run.json()["id"])
        assert app.state.backup_tasks.runs == [
            backup_id
        ]

        history = client.get(
            "/api/v1/backups"
        )
        assert history.status_code == 200
        assert len(history.json()["items"]) == 1

        with app.state.database.session() as session:
            item = session.get(
                BackupSet,
                backup_id,
            )
            assert item is not None
            item.state = "COMPLETED"
            item.restic_snapshot_id = "a" * 64
            item.verification_state = "PASSED"
            session.commit()

        verify = client.post(
            f"/api/v1/backups/{backup_id}/verify"
        )
        assert verify.status_code == 202
        assert app.state.backup_tasks.verifies == [
            backup_id
        ]
        assert verify.json()["verification_state"] == "PENDING"
