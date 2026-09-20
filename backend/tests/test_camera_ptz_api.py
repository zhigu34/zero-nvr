from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.core.security import SecretStore
from app.main import create_app
from app.modules.auth.models import SecretRecord
from app.modules.cameras.models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    DeviceCredential,
    DeviceEndpoint,
)


ADMIN_PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="camera-ptz-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'camera-ptz.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def test_ptz_api_uses_encrypted_onvif_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    captured = {}

    async def fake_move(self, **kwargs):
        captured["move"] = kwargs

    async def fake_stop(self, **kwargs):
        captured["stop"] = kwargs

    monkeypatch.setattr(
        "app.modules.cameras.api.OnvifAdapter.ptz_move",
        fake_move,
    )
    monkeypatch.setattr(
        "app.modules.cameras.api.OnvifAdapter.ptz_stop",
        fake_stop,
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
                name="PTZ Camera",
                adapter_type="onvif",
                enabled=True,
                capabilities_json={
                    "onvif_services": [
                        "Media",
                        "PTZ",
                    ]
                },
            )
            session.add(device)
            session.flush()

            endpoint = DeviceEndpoint(
                device_id=device.id,
                type="onvif",
                host="192.168.10.30",
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
                    "username": "ptz-admin",
                    "password": "ptz-secret",
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

            camera = Camera(
                device_id=device.id,
                channel_key="default",
                name="PTZ Camera",
                enabled=True,
            )
            session.add(camera)
            session.flush()

            profile = CameraStreamProfile(
                camera_id=camera.id,
                adapter_profile_key="ptz-main",
                name="Main",
                has_audio=False,
                status="online",
            )
            session.add(profile)
            session.flush()
            session.add(
                CameraStreamBinding(
                    camera_id=camera.id,
                    purpose="LIVE_HIGH",
                    stream_profile_id=profile.id,
                    selection_mode="auto",
                )
            )
            session.commit()
            camera_id = camera.id

        listed = client.get("/api/v1/cameras")
        assert listed.status_code == 200
        summary = next(
            item
            for item in listed.json()
            if item["id"] == str(camera_id)
        )
        assert summary["ptz_capable"] is True

        moved = client.post(
            f"/api/v1/cameras/{camera_id}/ptz/move",
            json={
                "pan": 0.6,
                "tilt": -0.4,
                "zoom": 0,
            },
        )
        assert moved.status_code == 200
        assert moved.json() == {"ok": True}
        assert captured["move"]["host"] == "192.168.10.30"
        assert captured["move"]["username"] == "ptz-admin"
        assert captured["move"]["password"] == "ptz-secret"
        assert captured["move"][
            "preferred_profile_tokens"
        ] == ("ptz-main",)

        stopped = client.post(
            f"/api/v1/cameras/{camera_id}/ptz/stop"
        )
        assert stopped.status_code == 200
        assert stopped.json() == {"ok": True}
        assert captured["stop"]["password"] == "ptz-secret"

        invalid = client.post(
            f"/api/v1/cameras/{camera_id}/ptz/move",
            json={
                "pan": 0,
                "tilt": 0,
                "zoom": 0,
            },
        )
        assert invalid.status_code == 400
        assert (
            invalid.json()["error"]["code"]
            == "camera_ptz_move_invalid"
        )

    with app.state.database.session() as session:
        stored = session.scalar(
            select(SecretRecord).where(
                SecretRecord.kind
                == "onvif_credential"
            )
        )
        assert stored is not None
        assert b"ptz-secret" not in stored.encrypted_payload
