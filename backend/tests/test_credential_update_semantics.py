from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app


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


def test_storage_credential_update_actions(tmp_path: Path) -> None:
    app = make_app(tmp_path)

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
