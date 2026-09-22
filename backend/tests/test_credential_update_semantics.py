from __future__ import annotations

from pathlib import Path
import uuid

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.core.errors import ApiError
from app.main import create_app
from app.modules.storage.service import StorageTargetService
from app.modules.system.frigate import FrigateProviderSettingsService
from app.modules.system.models import SystemSetting


PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="credential-update-test-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'credential-update.db'}",
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
            "password": PASSWORD,
        },
    )
    assert created.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200


def test_oidc_secret_update_actions(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        created = client.post(
            "/api/v1/oidc/providers",
            json={
                "key": "example",
                "name": "Example",
                "enabled": True,
                "issuer": "https://id.example.test",
                "client_id": "zero-nvr",
                "client_secret": "initial-oidc-secret",
                "auto_provision": False,
                "email_linking": False,
                "default_role_ids": [],
            },
        )
        assert created.status_code == 201
        assert created.json()["client_secret_configured"] is True

        ambiguous = client.patch(
            "/api/v1/oidc/providers/example",
            json={
                "client_secret": "should-be-rejected",
            },
        )
        assert ambiguous.status_code == 400
        assert (
            ambiguous.json()["error"]["code"]
            == "oidc_client_secret_update_invalid"
        )

        kept = client.patch(
            "/api/v1/oidc/providers/example",
            json={
                "name": "Example kept",
                "client_secret_action": "keep",
            },
        )
        assert kept.status_code == 200
        assert kept.json()["client_secret_configured"] is True

        replaced = client.patch(
            "/api/v1/oidc/providers/example",
            json={
                "client_secret_action": "replace",
                "client_secret": "replacement-oidc-secret",
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["client_secret_configured"] is True

        cleared = client.patch(
            "/api/v1/oidc/providers/example",
            json={"client_secret_action": "clear"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["client_secret_configured"] is False


def test_notification_url_update_actions(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        created = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "Ops",
                "enabled": True,
                "config": {},
                "url": "json://notify.example.test",
            },
        )
        assert created.status_code == 201
        target_id = created.json()["id"]
        assert created.json()["url_configured"] is True

        ambiguous = client.patch(
            f"/api/v1/notification-targets/{target_id}",
            json={"url": "json://replacement.example.test"},
        )
        assert ambiguous.status_code == 400

        kept = client.patch(
            f"/api/v1/notification-targets/{target_id}",
            json={
                "name": "Ops kept",
                "url_action": "keep",
            },
        )
        assert kept.status_code == 200
        assert kept.json()["url_configured"] is True

        replaced = client.patch(
            f"/api/v1/notification-targets/{target_id}",
            json={
                "url_action": "replace",
                "url": "json://replacement.example.test",
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["url_configured"] is True

        cleared = client.patch(
            f"/api/v1/notification-targets/{target_id}",
            json={"url_action": "clear"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["url_configured"] is False


def test_storage_credential_update_actions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    monkeypatch.setattr(
        StorageTargetService,
        "test_target",
        lambda self, **_kwargs: None,
    )

    with TestClient(app) as client:
        setup_admin(client)

        created = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "rclone",
                "role": "archive",
                "name": "Archive",
                "enabled": True,
                "config": {
                    "remote": "archive",
                    "base_path": "zero-nvr",
                },
                "rclone_config": (
                    "[archive]\n"
                    "type = s3\n"
                    "access_key_id = initial\n"
                ),
            },
        )
        assert created.status_code == 201
        target_id = created.json()["id"]
        assert created.json()["credentials_configured"] is True

        ambiguous = client.patch(
            f"/api/v1/storage/targets/{target_id}",
            json={
                "rclone_config": (
                    "[archive]\n"
                    "type = s3\n"
                    "access_key_id = ambiguous\n"
                )
            },
        )
        assert ambiguous.status_code == 400

        kept = client.patch(
            f"/api/v1/storage/targets/{target_id}",
            json={
                "name": "Archive kept",
                "rclone_config_action": "keep",
            },
        )
        assert kept.status_code == 200
        assert kept.json()["credentials_configured"] is True

        replaced = client.patch(
            f"/api/v1/storage/targets/{target_id}",
            json={
                "rclone_config_action": "replace",
                "rclone_config": (
                    "[archive]\n"
                    "type = s3\n"
                    "access_key_id = replacement\n"
                ),
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["credentials_configured"] is True

        cleared = client.patch(
            f"/api/v1/storage/targets/{target_id}",
            json={"rclone_config_action": "clear"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["credentials_configured"] is False


def test_backup_credential_update_actions(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        created = client.post(
            "/api/v1/backups/policies",
            json={
                "name": "Nightly",
                "enabled": True,
                "repository": "/tmp/zero-nvr-backup",
                "credentials": {
                    "password": "initial-restic-password",
                    "environment": {},
                },
                "initialize_if_missing": False,
                "database_backend": "sqlite",
                "schedule": {},
                "retention": {"keep_last": 7},
                "verify_after_backup": True,
                "repository_check_schedule": {},
                "include_deployment_config": False,
            },
        )
        assert created.status_code == 201
        policy_id = created.json()["id"]
        assert created.json()["credentials_configured"] is True

        ambiguous = client.patch(
            f"/api/v1/backups/policies/{policy_id}",
            json={
                "credentials": {
                    "password": "ambiguous-restic-password",
                }
            },
        )
        assert ambiguous.status_code == 400

        kept = client.patch(
            f"/api/v1/backups/policies/{policy_id}",
            json={
                "name": "Nightly kept",
                "credentials_action": "keep",
            },
        )
        assert kept.status_code == 200
        assert kept.json()["credentials_configured"] is True

        replaced = client.patch(
            f"/api/v1/backups/policies/{policy_id}",
            json={
                "credentials_action": "replace",
                "credentials": {
                    "password": "replacement-restic-password",
                },
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["credentials_configured"] is True

        cleared = client.patch(
            f"/api/v1/backups/policies/{policy_id}",
            json={"credentials_action": "clear"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["credentials_configured"] is False


def test_frigate_credential_update_actions(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        base = {
            "enabled": False,
            "mode": "external",
            "base_url": "http://frigate:5000",
            "camera_map": [],
            "mqtt_enabled": False,
            "mqtt_host": None,
            "mqtt_port": 1883,
            "mqtt_topic_prefix": "frigate",
            "mqtt_tls": False,
        }

        created = client.put(
            "/api/v1/system/integrations/frigate",
            json={
                **base,
                "credentials_action": "replace",
                "credentials": {
                    "http_bearer_token": "initial-frigate-token",
                },
            },
        )
        assert created.status_code == 200
        assert created.json()["credentials_configured"] is True

        ambiguous = client.put(
            "/api/v1/system/integrations/frigate",
            json={
                **base,
                "credentials": {
                    "http_bearer_token": "ambiguous-frigate-token",
                },
            },
        )
        assert ambiguous.status_code == 400
        assert (
            ambiguous.json()["error"]["code"]
            == "frigate_credentials_update_invalid"
        )

        kept = client.put(
            "/api/v1/system/integrations/frigate",
            json={
                **base,
                "base_url": "http://frigate-new:5000",
                "credentials_action": "keep",
            },
        )
        assert kept.status_code == 200
        assert kept.json()["credentials_configured"] is True

        replaced = client.put(
            "/api/v1/system/integrations/frigate",
            json={
                **base,
                "credentials_action": "replace",
                "credentials": {
                    "http_password": "replacement-frigate-password",
                },
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["credentials_configured"] is True

        cleared = client.put(
            "/api/v1/system/integrations/frigate",
            json={
                **base,
                "credentials_action": "clear",
            },
        )
        assert cleared.status_code == 200
        assert cleared.json()["credentials_configured"] is False


def test_storage_validation_failure_preserves_current_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        created = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "rclone",
                "role": "archive",
                "name": "Atomic archive",
                "enabled": True,
                "config": {
                    "remote": "archive",
                    "base_path": "zero-nvr",
                },
                "rclone_config": (
                    "[archive]\n"
                    "type = s3\n"
                    "access_key_id = initial\n"
                ),
            },
        )
        assert created.status_code == 201
        target_id = uuid.UUID(created.json()["id"])

        service = StorageTargetService(
            app.state.settings
        )
        with app.state.database.session() as session:
            target = service.get(
                session,
                target_id,
            )
            old_ref = target.credential_secret_ref
            assert old_ref is not None
            assert "access_key_id = initial" in (
                service.resolve_rclone(
                    session,
                    target=target,
                ).config_text
            )

        def reject_candidate(
            _self,
            **_kwargs,
        ):
            raise ApiError(
                status_code=409,
                code="rclone_probe_failed",
                message="candidate rejected",
            )

        monkeypatch.setattr(
            StorageTargetService,
            "test_target",
            reject_candidate,
        )

        rejected = client.patch(
            f"/api/v1/storage/targets/{target_id}",
            json={
                "rclone_config_action": "replace",
                "rclone_config": (
                    "[archive]\n"
                    "type = s3\n"
                    "access_key_id = rejected\n"
                ),
            },
        )
        assert rejected.status_code == 409

        with app.state.database.session() as session:
            target = service.get(
                session,
                target_id,
            )
            assert target.credential_secret_ref == old_ref
            resolved = service.resolve_rclone(
                session,
                target=target,
            )
            assert "access_key_id = initial" in (
                resolved.config_text
            )
            assert "access_key_id = rejected" not in (
                resolved.config_text
            )


def test_frigate_validation_failure_preserves_current_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        base = {
            "mode": "external",
            "base_url": "http://frigate:5000",
            "camera_map": [],
            "mqtt_enabled": False,
            "mqtt_host": None,
            "mqtt_port": 1883,
            "mqtt_topic_prefix": "frigate",
            "mqtt_tls": False,
        }

        created = client.put(
            "/api/v1/system/integrations/frigate",
            json={
                **base,
                "enabled": False,
                "credentials_action": "replace",
                "credentials": {
                    "http_bearer_token": "current-token",
                },
            },
        )
        assert created.status_code == 200

        with app.state.database.session() as session:
            setting = session.get(
                SystemSetting,
                "ai.frigate",
            )
            assert setting is not None
            old_ref = str(
                setting.value_json["secret_ref"]
            )

        def reject_candidate(
            *,
            base_url: str,
            credentials,
        ) -> None:
            del base_url, credentials
            raise ApiError(
                status_code=401,
                code="frigate_request_failed",
                message="candidate rejected",
            )

        monkeypatch.setattr(
            FrigateProviderSettingsService,
            "_validate_external_credentials",
            staticmethod(reject_candidate),
        )

        rejected = client.put(
            "/api/v1/system/integrations/frigate",
            json={
                **base,
                "enabled": True,
                "credentials_action": "replace",
                "credentials": {
                    "http_bearer_token": "rejected-token",
                },
            },
        )
        assert rejected.status_code == 401

        with app.state.database.session() as session:
            setting = session.get(
                SystemSetting,
                "ai.frigate",
            )
            assert setting is not None
            assert (
                str(setting.value_json["secret_ref"])
                == old_ref
            )
            resolved = FrigateProviderSettingsService(
                app.state.settings
            ).get(session)
            assert resolved is not None
            assert (
                resolved.credentials.http_bearer_token
                == "current-token"
            )
