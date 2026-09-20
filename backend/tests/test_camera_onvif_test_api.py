from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.modules.cameras.api as camera_api
from app.core.config import Settings
from app.core.db import Base
from app.integrations.onvif import (
    OnvifDeviceInfo,
    OnvifInspection,
    OnvifIntegrationError,
    OnvifProfileProbe,
)
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import SecretRecord
from app.modules.cameras.models import Camera, Device, DiscoverySession


PASSWORD = "camera-admin-password"
STREAM_URI = (
    "rtsp://admin:stream-password@192.168.60.20/live"
    "?token=stream-secret-token"
)


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="onvif-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'onvif-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def setup_admin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "correct-horse-battery-staple",
        },
    )
    assert login.status_code == 200


def counts(app) -> dict[str, int]:
    models = {
        "cameras": Camera,
        "devices": Device,
        "secrets": SecretRecord,
        "audits": AuditEvent,
        "discoveries": DiscoverySession,
    }
    with app.state.database.session() as session:
        return {
            name: int(
                session.scalar(select(func.count()).select_from(model)) or 0
            )
            for name, model in models.items()
        }


def test_onvif_test_returns_safe_profile_metadata_without_persistence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    calls: list[dict[str, object]] = []

    class FakeOnvifAdapter:
        def __init__(self, _settings) -> None:
            pass

        async def inspect_device(
            self,
            *,
            host: str,
            port: int,
            username: str,
            password: str,
        ) -> OnvifInspection:
            calls.append(
                {
                    "host": host,
                    "port": port,
                    "username": username,
                    "password": password,
                }
            )
            return OnvifInspection(
                device=OnvifDeviceInfo(
                    manufacturer="Acme",
                    model="SecureCam",
                    firmware_version="3.4.5",
                    serial_number="SN-100",
                    hardware_id="HW-100",
                ),
                capabilities=("Media", "PTZ"),
                profiles=(
                    OnvifProfileProbe(
                        token="profile-main",
                        name="Main",
                        video_source_token="source-1",
                        codec="h265",
                        width=3840,
                        height=2160,
                        fps=25.0,
                        bitrate_kbps=8192,
                        gop_seconds=2.0,
                        audio_codec="aac",
                        has_audio=True,
                        stream_uri_available=True,
                        stream_uri=STREAM_URI,
                    ),
                ),
            )

    monkeypatch.setattr(camera_api, "OnvifAdapter", FakeOnvifAdapter)

    with TestClient(app) as client:
        setup_admin(client)
        before = counts(app)

        response = client.post(
            "/api/v1/cameras/onvif/test",
            json={
                "host": "192.168.60.20",
                "port": 80,
                "username": "camera-admin",
                "password": PASSWORD,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["device"] == {
            "manufacturer": "Acme",
            "model": "SecureCam",
            "firmware_version": "3.4.5",
            "serial_number": "SN-100",
            "hardware_id": "HW-100",
        }
        assert body["capabilities"] == ["Media", "PTZ"]
        assert body["profiles"][0]["token"] == "profile-main"
        assert body["profiles"][0]["codec"] == "h265"
        assert body["profiles"][0]["stream_uri_available"] is True

        serialized = json.dumps(body)
        assert "rtsp://" not in serialized
        assert "stream-password" not in serialized
        assert "stream-secret-token" not in serialized
        assert PASSWORD not in serialized

        assert calls == [
            {
                "host": "192.168.60.20",
                "port": 80,
                "username": "camera-admin",
                "password": PASSWORD,
            }
        ]
        assert counts(app) == before


def test_onvif_test_sanitizes_connection_failure_without_persistence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    class FailingOnvifAdapter:
        def __init__(self, _settings) -> None:
            pass

        async def inspect_device(self, **_kwargs):
            raise OnvifIntegrationError(
                "onvif_connection_failed",
                "Unable to inspect the ONVIF device.",
                status_code=422,
            )

    monkeypatch.setattr(camera_api, "OnvifAdapter", FailingOnvifAdapter)

    with TestClient(app) as client:
        setup_admin(client)
        before = counts(app)

        response = client.post(
            "/api/v1/cameras/onvif/test",
            json={
                "host": "192.168.60.20",
                "port": 80,
                "username": "camera-admin",
                "password": PASSWORD,
            },
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "onvif_connection_failed"
        serialized = json.dumps(body)
        assert PASSWORD not in serialized
        assert "camera-admin" not in serialized
        assert counts(app) == before


def test_onvif_test_rejects_url_in_host_before_adapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    class MustNotConstructAdapter:
        def __init__(self, _settings) -> None:
            raise AssertionError("adapter should not be constructed")

    monkeypatch.setattr(
        camera_api,
        "OnvifAdapter",
        MustNotConstructAdapter,
    )

    with TestClient(app) as client:
        setup_admin(client)
        response = client.post(
            "/api/v1/cameras/onvif/test",
            json={
                "host": "http://192.168.60.20/onvif/device_service",
                "port": 80,
                "username": "camera-admin",
                "password": PASSWORD,
            },
        )

        assert response.status_code == 422
