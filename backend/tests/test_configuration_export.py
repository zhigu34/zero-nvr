from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app


ADMIN_PASSWORD = (
    "correct-horse-battery-staple"
)


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key=(
            "configuration-export-test-"
            "secret-key-32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'config.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(
        app.state.database.engine
    )
    return app


def test_configuration_export_is_portable_and_secret_free(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    camera_secret = (
        "camera-password-never-export"
    )
    smtp_secret = (
        "smtp-password-never-export"
    )
    oidc_secret = (
        "oidc-secret-never-export"
    )
    frigate_secret = (
        "frigate-secret-never-export"
    )
    rclone_secret = (
        "rclone-secret-never-export"
    )

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "email": "admin@example.com",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 201
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200

        camera = client.post(
            "/api/v1/cameras",
            json={
                "mode": "manual_rtsp",
                "name": "Front Door",
                "location": "Entrance",
                "primary_stream": {
                    "name": "Main",
                    "rtsp_url": (
                        "rtsp://alice:"
                        + camera_secret
                        + "@10.0.0.8/live"
                    ),
                },
                "secondary_stream": None,
            },
        )
        assert camera.status_code == 201

        notification = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "SMTP",
                "enabled": True,
                "config": {
                    "notify_type": "warning",
                    "password_reset": False,
                },
                "url": (
                    "mailto://mailer:"
                    + smtp_secret
                    + "@smtp.example.test"
                ),
            },
        )
        assert notification.status_code == 201

        roles = client.get(
            "/api/v1/roles"
        ).json()
        viewer = next(
            item
            for item in roles
            if item["name"] == "Viewer"
        )
        oidc = client.post(
            "/api/v1/oidc/providers",
            json={
                "key": "authentik",
                "name": "Authentik",
                "issuer": (
                    "https://id.example.test"
                ),
                "client_id": "zero-nvr",
                "client_secret": oidc_secret,
                "auto_provision": True,
                "email_linking": True,
                "default_role_ids": [
                    viewer["id"]
                ],
            },
        )
        assert oidc.status_code == 201

        storage = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "rclone",
                "role": "archive",
                "name": "Remote archive",
                "enabled": True,
                "config": {
                    "remote": "archive",
                    "base_path": "zero-nvr",
                    "default_archive": True,
                },
                "rclone_config": (
                    "[archive]\n"
                    "type = s3\n"
                    "access_key_id = test\n"
                    "secret_access_key = "
                    + rclone_secret
                    + "\n"
                ),
            },
        )
        assert storage.status_code == 201

        frigate = client.put(
            "/api/v1/system/integrations/frigate",
            json={
                "enabled": False,
                "mode": "external",
                "base_url": (
                    "https://frigate.example.test"
                ),
                "camera_map": [],
                "mqtt_enabled": False,
                "mqtt_host": None,
                "mqtt_port": 1883,
                "mqtt_topic_prefix": "frigate",
                "mqtt_tls": False,
                "credentials": {
                    "http_bearer_token": (
                        frigate_secret
                    ),
                },
                "replace_credentials": True,
            },
        )
        assert frigate.status_code == 200

        exported = client.get(
            "/api/v1/system/configuration/export"
        )
        assert exported.status_code == 200
        assert exported.headers[
            "content-type"
        ].startswith("application/json")
        assert "attachment;" in exported.headers[
            "content-disposition"
        ]
        assert exported.headers[
            "cache-control"
        ] == "no-store, max-age=0"

        body = exported.json()
        assert body["format"] == (
            "zero-nvr.configuration"
        )
        assert body["format_version"] == 1
        assert body["secrets_included"] is False

        serialized = json.dumps(
            body,
            sort_keys=True,
        )
        for secret in (
            camera_secret,
            smtp_secret,
            oidc_secret,
            frigate_secret,
            rclone_secret,
        ):
            assert secret not in serialized

        for forbidden in (
            "secret_ref",
            "encrypted_payload",
            "token_hash",
            "password_hash",
        ):
            assert forbidden not in serialized

        camera_exports = body[
            "sections"
        ]["cameras"]["stream_profiles"]
        assert len(camera_exports) == 1
        assert (
            camera_exports[0][
                "stream_uri_configured"
            ]
            is True
        )

        notification_exports = body[
            "sections"
        ]["notification_targets"]
        assert (
            notification_exports[0][
                "url_configured"
            ]
            is True
        )

        storage_exports = body[
            "sections"
        ]["storage_targets"]
        assert (
            storage_exports[0][
                "credentials_configured"
            ]
            is True
        )

        oidc_exports = body[
            "sections"
        ]["oidc_providers"]
        assert (
            oidc_exports[0][
                "client_secret_configured"
            ]
            is True
        )

        frigate_export = body[
            "sections"
        ]["frigate"]
        assert frigate_export is not None
        assert (
            frigate_export[
                "credentials_configured"
            ]
            is True
        )

        audit = client.get(
            "/api/v1/audit",
            params={
                "action": (
                    "system.configuration.export"
                )
            },
        )
        assert audit.status_code == 200
        actions = [
            item["action"]
            for item in audit.json()["items"]
        ]
        assert (
            "system.configuration.export"
            in actions
        )



def test_configuration_import_validation_checks_refs_and_secrets(
    tmp_path: Path,
) -> None:
    import copy

    app = make_app(tmp_path)
    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "email": "admin@example.com",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 201
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200

        camera = client.post(
            "/api/v1/cameras",
            json={
                "mode": "manual_rtsp",
                "name": "Import Camera",
                "location": None,
                "primary_stream": {
                    "name": "Main",
                    "rtsp_url": (
                        "rtsp://camera-user:"
                        "camera-import-secret"
                        "@10.0.0.9/live"
                    ),
                },
                "secondary_stream": None,
            },
        )
        assert camera.status_code == 201

        exported = client.get(
            "/api/v1/system/configuration/export"
        )
        assert exported.status_code == 200
        bundle = exported.json()

        validated = client.post(
            (
                "/api/v1/system/"
                "configuration/import/validate"
            ),
            json={"bundle": bundle},
        )
        assert validated.status_code == 200
        result = validated.json()
        assert result["valid"] is True
        assert (
            result["format"]
            == "zero-nvr.configuration"
        )
        assert result[
            "section_counts"
        ]["cameras"] >= 3
        assert any(
            item["credential"]
            == "stream_uri"
            for item in result[
                "credentials_required"
            ]
        )

        with_secret = copy.deepcopy(
            bundle
        )
        with_secret["sections"][
            "oidc_providers"
        ] = [
            {
                "id": (
                    "11111111-1111-1111-"
                    "1111-111111111111"
                ),
                "key": "bad",
                "name": "Bad",
                "client_secret": (
                    "must-not-be-imported"
                ),
            }
        ]
        rejected = client.post(
            (
                "/api/v1/system/"
                "configuration/import/validate"
            ),
            json={"bundle": with_secret},
        )
        assert rejected.status_code == 400
        assert (
            rejected.json()["error"]["code"]
            == "configuration_import_secret_field"
        )

        broken = copy.deepcopy(bundle)
        broken_binding = broken[
            "sections"
        ]["cameras"]["stream_bindings"][0]
        broken_binding[
            "stream_profile_id"
        ] = (
            "22222222-2222-2222-"
            "2222-222222222222"
        )
        invalid_ref = client.post(
            (
                "/api/v1/system/"
                "configuration/import/validate"
            ),
            json={"bundle": broken},
        )
        assert invalid_ref.status_code == 400
        assert (
            invalid_ref.json()["error"]["code"]
            == (
                "configuration_import_reference_invalid"
            )
        )
