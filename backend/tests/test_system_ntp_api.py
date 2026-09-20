from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.core.security import SecretStore
from app.main import create_app
from app.modules.auth.models import SecretRecord
from app.modules.cameras.models import (
    Device,
    DeviceCredential,
    DeviceEndpoint,
)


ADMIN_PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="system-ntp-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'system-ntp.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def test_apply_camera_ntp_uses_saved_servers_and_encrypted_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    calls = []

    async def fake_configure(self, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "app.modules.system.api.OnvifAdapter.configure_ntp",
        fake_configure,
    )

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
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

        with app.state.database.session() as session:
            device = Device(
                name="Front Door Device",
                adapter_type="onvif",
                enabled=True,
                capabilities_json={},
            )
            session.add(device)
            session.flush()

            endpoint = DeviceEndpoint(
                device_id=device.id,
                type="onvif",
                host="192.168.10.40",
                port=80,
                scheme="http",
                priority=100,
                enabled=True,
                metadata_json={},
            )
            session.add(endpoint)
            session.flush()

            encrypted = SecretStore(
                app.state.settings
            ).encrypt_json(
                {
                    "username": "onvif-admin",
                    "password": "onvif-secret",
                }
            )
            secret = SecretRecord(
                kind="onvif_credential",
                owner_type="device",
                owner_id=device.id,
                key_id=encrypted.key_id,
                encrypted_payload=encrypted.ciphertext,
                version=encrypted.version,
            )
            session.add(secret)
            session.flush()
            session.add(
                DeviceCredential(
                    device_id=device.id,
                    endpoint_id=endpoint.id,
                    kind="onvif",
                    secret_ref=secret.id,
                )
            )
            session.commit()

        saved = client.patch(
            "/api/v1/system/settings",
            json={
                "general": {
                    "camera_ntp_servers": [
                        "pool.ntp.org",
                        "192.0.2.10",
                    ]
                }
            },
        )
        assert saved.status_code == 200

        applied = client.post(
            "/api/v1/system/settings/camera-ntp/apply"
        )
        assert applied.status_code == 200
        body = applied.json()
        assert body["mode"] == "manual"
        assert body["total_devices"] == 1
        assert body["updated"] == 1
        assert body["failed"] == 0
        assert body["results"][0]["status"] == "UPDATED"

        assert len(calls) == 1
        assert calls[0]["host"] == "192.168.10.40"
        assert calls[0]["username"] == "onvif-admin"
        assert calls[0]["password"] == "onvif-secret"
        assert calls[0]["servers"] == (
            "pool.ntp.org",
            "192.0.2.10",
        )

        serialized = str(body)
        assert "onvif-secret" not in serialized
        assert "onvif-admin" not in serialized

        assert client.patch(
            "/api/v1/system/settings",
            json={
                "general": {
                    "camera_ntp_servers": []
                }
            },
        ).status_code == 200
        dhcp = client.post(
            "/api/v1/system/settings/camera-ntp/apply"
        )
        assert dhcp.status_code == 200
        assert dhcp.json()["mode"] == "dhcp"
        assert calls[-1]["servers"] == ()
