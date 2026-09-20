from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

import app.modules.cameras.api as camera_api
from app.core.config import Settings
from app.core.db import Base
from app.integrations.zlm import (
    ZlmIntegrationError,
    ZlmMediaProbe,
    ZlmTrackProbe,
)
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import SecretRecord
from app.modules.cameras.models import (
    Camera,
    CameraStreamProfile,
    Device,
    DeviceEndpoint,
)


PASSWORD = "correct-horse-battery-staple"
PRIMARY_URL = (
    "rtsp://alice:camera-password@10.0.0.21:8554/live/main"
    "?token=primary-secret"
)
SECONDARY_URL = (
    "rtsp://alice:camera-password@10.0.0.21:8554/live/sub"
    "?token=secondary-secret"
)


def make_app(
    tmp_path: Path,
    *,
    zlm_api_secret: SecretStr | None = SecretStr("test-zlm-api-secret"),
):
    settings = Settings(
        secret_key="camera-probe-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'camera-probe.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
        zlm_api_secret=zlm_api_secret,
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
        json={"username": "admin", "password": PASSWORD},
    )
    assert login.status_code == 200


def probe_payload() -> dict[str, object]:
    return {
        "mode": "manual_rtsp",
        "name": "Front Door",
        "location": "Entrance",
        "primary_stream": {
            "name": "Main",
            "rtsp_url": PRIMARY_URL,
        },
        "secondary_stream": {
            "name": "Sub",
            "rtsp_url": SECONDARY_URL,
        },
    }


def persistence_counts(app) -> dict[str, int]:
    models = {
        "cameras": Camera,
        "devices": Device,
        "device_endpoints": DeviceEndpoint,
        "stream_profiles": CameraStreamProfile,
        "secrets": SecretRecord,
        "audit_events": AuditEvent,
    }
    with app.state.database.session() as session:
        return {
            name: int(
                session.scalar(select(func.count()).select_from(model)) or 0
            )
            for name, model in models.items()
        }


class SuccessfulProbeAdapter:
    calls: list[str] = []

    def __init__(self, _settings) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def probe_rtsp_source(self, source_url: str) -> ZlmMediaProbe:
        self.calls.append(source_url)
        if source_url == PRIMARY_URL:
            return ZlmMediaProbe(
                stream="probe-primary",
                video=ZlmTrackProbe(
                    kind="video",
                    codec="h265",
                    ready=True,
                    width=3840,
                    height=2160,
                    fps=25.0,
                    gop_seconds=2.0,
                ),
                audio=ZlmTrackProbe(
                    kind="audio",
                    codec="aac",
                    ready=True,
                    sample_rate=48000,
                    channels=2,
                ),
            )

        return ZlmMediaProbe(
            stream="probe-secondary",
            video=ZlmTrackProbe(
                kind="video",
                codec="h264",
                ready=True,
                width=640,
                height=360,
                fps=10.0,
                gop_seconds=1.0,
            ),
            audio=None,
        )


def test_camera_test_returns_safe_media_info_without_persistence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        before = persistence_counts(app)

        SuccessfulProbeAdapter.calls = []
        monkeypatch.setattr(
            camera_api,
            "ZlmAdapter",
            SuccessfulProbeAdapter,
        )

        response = client.post(
            "/api/v1/cameras/test",
            json=probe_payload(),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert [item["role"] for item in body["streams"]] == [
            "primary",
            "secondary",
        ]

        primary = body["streams"][0]
        assert primary["name"] == "Main"
        assert primary["video"] == {
            "kind": "video",
            "codec": "h265",
            "ready": True,
            "width": 3840,
            "height": 2160,
            "fps": 25.0,
            "gop_seconds": 2.0,
            "sample_rate": None,
            "channels": None,
        }
        assert primary["audio"]["codec"] == "aac"
        assert primary["audio"]["sample_rate"] == 48000

        secondary = body["streams"][1]
        assert secondary["video"]["codec"] == "h264"
        assert secondary["audio"] is None

        assert SuccessfulProbeAdapter.calls == [
            PRIMARY_URL,
            SECONDARY_URL,
        ]

        serialized = json.dumps(body)
        assert "camera-password" not in serialized
        assert "primary-secret" not in serialized
        assert "secondary-secret" not in serialized
        assert "rtsp://" not in serialized

        after = persistence_counts(app)
        assert after == before


def test_camera_test_reports_unconfigured_zlm_without_persistence(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path, zlm_api_secret=None)

    with TestClient(app) as client:
        setup_admin(client)
        before = persistence_counts(app)

        response = client.post(
            "/api/v1/cameras/test",
            json=probe_payload(),
        )

        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "zlm_not_configured"

        serialized = json.dumps(body)
        assert "camera-password" not in serialized
        assert "primary-secret" not in serialized
        assert "secondary-secret" not in serialized

        assert persistence_counts(app) == before


@pytest.mark.parametrize(
    ("code", "status_code", "message"),
    [
        (
            "camera_stream_probe_timeout",
            422,
            "The camera stream did not become ready in time.",
        ),
        (
            "zlm_operation_failed",
            502,
            "ZLMediaKit operation failed.",
        ),
    ],
)
def test_camera_test_sanitizes_probe_failures_and_does_not_persist(
    tmp_path: Path,
    monkeypatch,
    code: str,
    status_code: int,
    message: str,
) -> None:
    app = make_app(tmp_path)

    class FailingProbeAdapter:
        def __init__(self, _settings) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def probe_rtsp_source(self, source_url: str) -> ZlmMediaProbe:
            # Simulate an upstream failure while deliberately constructing the
            # exception from safe text only. Raw source URLs are never returned.
            raise ZlmIntegrationError(
                code,
                message,
                status_code=status_code,
            )

    with TestClient(app) as client:
        setup_admin(client)
        before = persistence_counts(app)

        monkeypatch.setattr(
            camera_api,
            "ZlmAdapter",
            FailingProbeAdapter,
        )
        response = client.post(
            "/api/v1/cameras/test",
            json=probe_payload(),
        )

        assert response.status_code == status_code
        body = response.json()
        assert body["error"]["code"] == code
        assert body["error"]["details"] == {"stream": "primary"}

        serialized = json.dumps(body)
        assert "camera-password" not in serialized
        assert "primary-secret" not in serialized
        assert "secondary-secret" not in serialized
        assert "rtsp://" not in serialized

        assert persistence_counts(app) == before


def test_camera_test_rejects_invalid_rtsp_before_zlm(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    class MustNotConstructAdapter:
        def __init__(self, _settings) -> None:
            pytest.fail("ZLM adapter must not be constructed for invalid RTSP")

    with TestClient(app) as client:
        setup_admin(client)
        before = persistence_counts(app)

        monkeypatch.setattr(
            camera_api,
            "ZlmAdapter",
            MustNotConstructAdapter,
        )
        payload = probe_payload()
        payload["primary_stream"]["rtsp_url"] = "https://example.com/not-rtsp"

        response = client.post(
            "/api/v1/cameras/test",
            json=payload,
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_rtsp_url"
        assert persistence_counts(app) == before
