from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.core.security import SecretStore
from app.main import create_app
from app.modules.auth.models import SecretRecord
from app.modules.notifications.models import NotificationTarget
from app.modules.notifications.service import SECURITY_EMAIL_NAMESPACE
from app.modules.system.models import SystemSetting


ADMIN_PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="smtp-target-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'smtp-target.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def setup_admin(client: TestClient) -> None:
    created = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": ADMIN_PASSWORD,
        },
    )
    assert created.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": ADMIN_PASSWORD,
        },
    )
    assert login.status_code == 200


def test_smtp_target_persistence_and_security_email_selection(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    smtp_password = "smtp-password-never-export"

    with TestClient(app) as client:
        setup_admin(client)

        created = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "Security SMTP",
                "kind": "smtp",
                "enabled": True,
                "config": {
                    "host": "SMTP.Example.TEST",
                    "port": 587,
                    "security": "starttls",
                    "from_address": "security@example.test",
                    "from_name": "zero-nvr",
                },
                "smtp_credentials": {
                    "username": "mailer",
                    "password": smtp_password,
                },
            },
        )
        assert created.status_code == 201
        body = created.json()
        target_id = uuid.UUID(body["id"])
        assert body["kind"] == "smtp"
        assert body["config"] == {
            "host": "smtp.example.test",
            "port": 587,
            "security": "starttls",
            "from_address": "security@example.test",
            "from_name": "zero-nvr",
        }
        assert body["url_configured"] is False
        assert body["credentials_configured"] is True
        assert smtp_password not in created.text

        with app.state.database.session() as session:
            target = session.get(
                NotificationTarget,
                target_id,
            )
            assert target is not None
            assert target.kind == "smtp"
            assert target.secret_ref is not None
            secret_ref = target.secret_ref

            record = session.get(
                SecretRecord,
                secret_ref,
            )
            assert record is not None
            assert record.kind == "smtp_credentials"
            assert smtp_password.encode() not in (
                record.encrypted_payload
            )

            secret = SecretStore(
                app.state.settings
            ).read_json(
                session,
                secret_ref,
                kind="smtp_credentials",
                owner_type="notification_target",
                owner_id=target_id,
            )
            assert secret == {
                "username": "mailer",
                "password": smtp_password,
            }
            assert session.get(
                SystemSetting,
                SECURITY_EMAIL_NAMESPACE,
            ) is None

        selected = client.put(
            "/api/v1/notification-targets/security-email-default",
            json={"target_id": str(target_id)},
        )
        assert selected.status_code == 200
        assert selected.json() == {
            "target_id": str(target_id)
        }

        current = client.get(
            "/api/v1/notification-targets/security-email-default"
        )
        assert current.status_code == 200
        assert current.json() == {
            "target_id": str(target_id)
        }

        with app.state.database.session() as session:
            setting = session.get(
                SystemSetting,
                SECURITY_EMAIL_NAMESPACE,
            )
            assert setting is not None
            assert setting.value_json == {
                "target_id": str(target_id)
            }
            matching = list(
                session.scalars(
                    select(SystemSetting).where(
                        SystemSetting.namespace
                        == SECURITY_EMAIL_NAMESPACE
                    )
                )
            )
            assert len(matching) == 1

        apprise = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "Push",
                "kind": "apprise",
                "enabled": True,
                "config": {
                    "notify_type": "warning",
                },
                "url": "json://notify.example.test",
            },
        )
        assert apprise.status_code == 201

        rejected = client.put(
            "/api/v1/notification-targets/security-email-default",
            json={"target_id": apprise.json()["id"]},
        )
        assert rejected.status_code == 400
        assert (
            rejected.json()["error"]["code"]
            == "security_email_target_invalid"
        )

        exported = client.get(
            "/api/v1/system/configuration/export"
        )
        assert exported.status_code == 200
        serialized = json.dumps(
            exported.json(),
            sort_keys=True,
        )
        assert smtp_password not in serialized
        smtp_export = next(
            item
            for item in exported.json()["sections"][
                "notification_targets"
            ]
            if item["id"] == str(target_id)
        )
        assert smtp_export["kind"] == "smtp"
        assert smtp_export["url_configured"] is False
        assert smtp_export["credentials_configured"] is True

        deleted = client.delete(
            f"/api/v1/notification-targets/{target_id}"
        )
        assert deleted.status_code == 204

        cleared = client.get(
            "/api/v1/notification-targets/security-email-default"
        )
        assert cleared.status_code == 200
        assert cleared.json() == {
            "target_id": None
        }

        with app.state.database.session() as session:
            setting = session.get(
                SystemSetting,
                SECURITY_EMAIL_NAMESPACE,
            )
            assert setting is not None
            assert setting.value_json == {
                "target_id": None
            }
            assert session.get(
                SecretRecord,
                secret_ref,
            ) is None
