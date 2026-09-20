from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.cameras.media_runtime import CameraMediaRuntimeService


ADMIN_PASSWORD = "correct-horse-battery-staple"


class FakeRecordingTasks:
    def __init__(self) -> None:
        self.runtime_reconciles = []

    def reconcile_runtime(self, camera_id) -> None:
        self.runtime_reconciles.append(camera_id)


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="camera-live-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'camera-live.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
        zlm_public_base_url="/zlm",
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    app.state.recording_tasks = FakeRecordingTasks()
    return app


def test_live_descriptor_uses_bound_profile_without_exposing_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    def fake_ensure(self, desired):
        return [item.reference for item in desired]

    monkeypatch.setattr(
        CameraMediaRuntimeService,
        "ensure_streams",
        fake_ensure,
    )

    with TestClient(app) as client:
        setup = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": ADMIN_PASSWORD,
            },
        )
        assert setup.status_code == 201

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": ADMIN_PASSWORD},
        )
        assert login.status_code == 200

        created = client.post(
            "/api/v1/cameras",
            json={
                "mode": "manual_rtsp",
                "name": "Front Door",
                "location": "Entrance",
                "primary_stream": {
                    "name": "Main",
                    "rtsp_url": (
                        "rtsp://alice:primary-secret@10.0.0.10/live/main"
                        "?token=primary-token"
                    ),
                },
                "secondary_stream": {
                    "name": "Sub",
                    "rtsp_url": (
                        "rtsp://alice:secondary-secret@10.0.0.10/live/sub"
                        "?token=secondary-token"
                    ),
                },
            },
        )
        assert created.status_code == 201
        camera_id = created.json()["id"]

        low = client.get(
            f"/api/v1/cameras/{camera_id}/live?quality=low"
        )
        assert low.status_code == 200
        low_body = low.json()
        assert low_body["purpose"] == "LIVE_LOW"
        assert low_body["transport"] == "hls"
        assert low_body["hls_url"].startswith(
            "/zlm/zero-nvr/profile-"
        )
        assert "/hls.m3u8?" in low_body["hls_url"]
        assert "zn_exp=" in low_body["hls_url"]
        assert "zn_sig=" in low_body["hls_url"]
        assert low_body["expires_at"]

        high = client.get(
            f"/api/v1/cameras/{camera_id}/live?quality=high"
        )
        assert high.status_code == 200
        high_body = high.json()
        assert high_body["purpose"] == "LIVE_HIGH"
        assert high_body["profile_id"] != low_body["profile_id"]

        serialized = json.dumps([low_body, high_body])
        assert "rtsp://" not in serialized
        assert "primary-secret" not in serialized
        assert "secondary-secret" not in serialized
        assert "primary-token" not in serialized
        assert "secondary-token" not in serialized

        disabled = client.post(
            f"/api/v1/cameras/{camera_id}/disable"
        )
        assert disabled.status_code == 200

        unavailable = client.get(
            f"/api/v1/cameras/{camera_id}/live"
        )
        assert unavailable.status_code == 409
        assert unavailable.json()["error"]["code"] == "camera_disabled"



def test_camera_snapshot_uses_internal_zlm_stream_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    captured: dict[str, str] = {}

    def fake_ensure(self, desired):
        return [item.reference for item in desired]

    class FakeZlmAdapter:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def snapshot(
            self,
            *,
            source_url: str,
            timeout_seconds: int,
            expire_seconds: int,
        ):
            captured["source_url"] = source_url
            assert timeout_seconds == 10
            assert expire_seconds == 3
            return b"\xff\xd8snapshot\xff\xd9", "image/jpeg"

    monkeypatch.setattr(
        CameraMediaRuntimeService,
        "ensure_streams",
        fake_ensure,
    )
    monkeypatch.setattr(
        "app.modules.cameras.api.ZlmAdapter",
        FakeZlmAdapter,
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

        created = client.post(
            "/api/v1/cameras",
            json={
                "mode": "manual_rtsp",
                "name": "Front Door",
                "location": "Entrance",
                "primary_stream": {
                    "name": "Main",
                    "rtsp_url": (
                        "rtsp://alice:camera-secret@10.0.0.10/main"
                        "?token=camera-token"
                    ),
                },
                "secondary_stream": None,
            },
        )
        assert created.status_code == 201
        camera_id = created.json()["id"]

        snapshot = client.get(
            f"/api/v1/cameras/{camera_id}/snapshot"
        )
        assert snapshot.status_code == 200
        assert snapshot.headers["content-type"].startswith(
            "image/jpeg"
        )
        assert snapshot.content.startswith(b"\xff\xd8")
        assert "attachment;" in snapshot.headers[
            "content-disposition"
        ]

    source_url = captured["source_url"]
    assert source_url.startswith(
        "rtsp://zlmediakit:554/zero-nvr/profile-"
    )
    assert "camera-secret" not in source_url
    assert "camera-token" not in source_url
    assert "10.0.0.10" not in source_url
