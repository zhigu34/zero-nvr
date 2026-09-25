from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.integrations.zlm import (
    ZlmMediaProbe,
    ZlmTrackProbe,
    ZlmWhepSession,
)
from app.modules.cameras.live_transcode import LiveTranscodeLease
from app.modules.cameras.media_runtime import ZlmStreamReference
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

    def fake_ensure(
        self,
        desired,
        *,
        wait_online_seconds=None,
    ):
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
        assert low.headers["cache-control"] == "private, no-store"
        low_body = low.json()
        assert low_body["purpose"] == "LIVE_LOW"
        assert low_body["transport"] == "hls"
        assert low_body["transports"] == ["webrtc", "hls"]
        assert low_body["hls_url"].startswith(
            "/zlm/zero-nvr/profile-"
        )
        assert "/hls.m3u8?" in low_body["hls_url"]
        assert "zn_exp=" in low_body["hls_url"]
        assert "zn_sig=" in low_body["hls_url"]
        assert "zn_sid=" in low_body["hls_url"]
        assert low_body["media_session_id"]
        assert low_body["expires_at"]
        assert low_body["ice_servers"] == []
        assert low_body["ice_error"] is None

        high = client.get(
            f"/api/v1/cameras/{camera_id}/live?quality=high"
        )
        assert high.status_code == 200
        high_body = high.json()
        assert high_body["purpose"] == "LIVE_HIGH"
        assert high_body["profile_id"] != low_body["profile_id"]
        assert (
            high_body["media_session_id"]
            != low_body["media_session_id"]
        )

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



def test_live_diagnostics_report_sanitized_zlm_track_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    def fake_ensure(
        self,
        desired,
        *,
        wait_online_seconds=None,
    ):
        return [item.reference for item in desired]

    class FakeZlmAdapter:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def media_probe(
            self,
            *,
            app: str,
            stream: str,
            schema: str,
        ):
            assert app == "zero-nvr"
            assert stream.startswith("profile-")
            assert schema == "rtsp"
            return ZlmMediaProbe(
                stream=stream,
                video=ZlmTrackProbe(
                    kind="video",
                    codec="h264",
                    ready=False,
                    width=1920,
                    height=1080,
                    fps=25.0,
                ),
                audio=None,
            )

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

        descriptor = client.get(
            f"/api/v1/cameras/{camera_id}/live?quality=high"
        )
        assert descriptor.status_code == 200
        media_session_id = descriptor.json()["media_session_id"]

        response = client.get(
            (
                f"/api/v1/cameras/{camera_id}/live/diagnostics"
                f"?quality=high&media_session_id={media_session_id}"
            )
        )
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "video_not_ready"
        assert body["source_online"] is True
        assert body["video_present"] is True
        assert body["video_ready"] is False
        assert body["codec"] == "h264"
        assert body["width"] == 1920
        assert body["height"] == 1080
        assert body["fps"] == 25.0

        serialized = json.dumps(body)
        assert "rtsp://" not in serialized
        assert "camera-secret" not in serialized
        assert "camera-token" not in serialized
        assert "10.0.0.10" not in serialized


def test_camera_snapshot_uses_internal_zlm_stream_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    captured: dict[str, str] = {}

    def fake_ensure(
        self,
        desired,
        *,
        wait_online_seconds=None,
    ):
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



def test_whep_live_session_is_authorized_proxied_and_revocable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    app.state.settings.zlm_webrtc_extern_ip = "192.0.2.10"
    app.state.settings.zlm_webrtc_port = 9000
    captured: dict[str, object] = {
        "ensure_calls": 0,
        "ensure_waits": [],
    }

    def fake_ensure(
        self,
        desired,
        *,
        wait_online_seconds=None,
    ):
        captured["ensure_calls"] = (
            int(captured["ensure_calls"]) + 1
        )
        waits = captured["ensure_waits"]
        assert isinstance(waits, list)
        waits.append(wait_online_seconds)
        return [item.reference for item in desired]

    class FakeZlmAdapter:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def whep_play(
            self,
            *,
            app: str,
            stream: str,
            offer_sdp: str,
            playback_params: dict[str, str],
            preferred_tcp: bool = False,
            candidate_udp: str | None = None,
            candidate_tcp: str | None = None,
        ):
            captured["app"] = app
            captured["stream"] = stream
            captured["offer_sdp"] = offer_sdp
            captured["playback_params"] = playback_params
            captured["preferred_tcp"] = preferred_tcp
            captured["candidate_udp"] = candidate_udp
            captured["candidate_tcp"] = candidate_tcp
            return ZlmWhepSession(
                answer_sdp=(
                    "v=0\r\no=- 2 2 IN IP4 127.0.0.1\r\n"
                ),
                session_id="session-123",
                session_token="cleanup-token",
            )

        def delete_webrtc(
            self,
            *,
            session_id: str,
            session_token: str,
        ) -> None:
            captured["deleted"] = (
                session_id,
                session_token,
            )

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

        unauthenticated = client.post(
            (
                "/api/v1/cameras/"
                "00000000-0000-0000-0000-000000000001"
                "/live/whep?media_session_id="
                "11111111-1111-1111-1111-111111111111"
            ),
            headers={"content-type": "application/sdp"},
            content="v=0\r\n",
        )
        assert unauthenticated.status_code == 401

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

        descriptor = client.get(
            f"/api/v1/cameras/{camera_id}/live?quality=high"
        )
        assert descriptor.status_code == 200
        assert captured["ensure_calls"] == 1
        assert captured["ensure_waits"] == [
            CameraMediaRuntimeService.live_start_timeout_seconds
        ]
        descriptor_body = descriptor.json()
        media_session_id = descriptor_body[
            "media_session_id"
        ]
        selected_profile_id = descriptor_body[
            "profile_id"
        ]

        offer = "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\n"
        whep = client.post(
            (
                f"/api/v1/cameras/{camera_id}/live/whep"
                f"?quality=low&media_session_id={media_session_id}"
            ),
            headers={
                "content-type": "application/sdp",
                "accept": "application/sdp",
            },
            content=offer,
        )
        assert whep.status_code == 201
        assert captured["ensure_calls"] == 1
        assert whep.headers["content-type"].startswith(
            "application/sdp"
        )
        assert whep.text.startswith("v=0")
        location = whep.headers["location"]
        assert location.startswith(
            f"/api/v1/cameras/{camera_id}/live/whep/"
        )

        assert captured["app"] == "zero-nvr"
        assert captured["stream"] == (
            "profile-"
            + selected_profile_id.replace("-", "")
        )
        assert captured["offer_sdp"] == offer
        assert captured["candidate_udp"] == "192.0.2.10:9000"
        assert captured["candidate_tcp"] == "192.0.2.10:9000"
        params = captured["playback_params"]
        assert isinstance(params, dict)
        assert "zn_exp" in params
        assert "zn_sig" in params
        assert params["zn_sid"] == media_session_id

        serialized = json.dumps(captured)
        assert "camera-secret" not in serialized
        assert "camera-token" not in serialized
        assert "rtsp://" not in serialized

        revoked = client.delete(
            (
                f"/api/v1/cameras/{camera_id}"
                f"/live/session/{media_session_id}"
            )
        )
        assert revoked.status_code == 204
        assert captured["deleted"] == (
            "session-123",
            "cleanup-token",
        )



def test_compatibility_transcode_uses_internal_stream_and_lease(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    captured: dict[str, object] = {}
    lease_id = uuid.UUID(
        "11111111-2222-3333-4444-555555555555"
    )

    def fake_ensure(
        self,
        desired,
        *,
        wait_online_seconds=None,
    ):
        return [item.reference for item in desired]

    class FakeTranscodes:
        def acquire(
            self,
            *,
            camera_id,
            owner_user_id,
            profile_id,
            source_url: str,
            has_audio: bool,
        ):
            captured["camera_id"] = str(camera_id)
            captured["owner_user_id"] = str(owner_user_id)
            captured["profile_id"] = str(profile_id)
            captured["source_url"] = source_url
            captured["has_audio"] = has_audio
            return LiveTranscodeLease(
                lease_id=lease_id,
                reference=ZlmStreamReference(
                    camera_id=camera_id,
                    profile_id=profile_id,
                    app="zero-nvr-compat",
                    stream=f"h264-{profile_id.hex}",
                ),
                acceleration="cpu",
            )

        def touch(
            self,
            value,
            *,
            camera_id,
            owner_user_id,
        ) -> bool:
            captured["touched"] = (
                str(value),
                str(camera_id),
                str(owner_user_id),
            )
            return True

        def release(
            self,
            value,
            *,
            camera_id=None,
            owner_user_id=None,
        ) -> bool:
            captured["released"] = (
                str(value),
                str(camera_id),
                str(owner_user_id),
            )
            return True

    monkeypatch.setattr(
        CameraMediaRuntimeService,
        "ensure_streams",
        fake_ensure,
    )
    app.state.live_transcodes = FakeTranscodes()

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

        descriptor = client.get(
            f"/api/v1/cameras/{camera_id}/live?quality=high"
        )
        assert descriptor.status_code == 200
        media_session_id = descriptor.json()[
            "media_session_id"
        ]

        compatibility = client.post(
            (
                f"/api/v1/cameras/{camera_id}"
                "/live/compatibility?quality=high"
                f"&media_session_id={media_session_id}"
            )
        )
        assert compatibility.status_code == 201
        body = compatibility.json()
        assert body["codec"] == "h264"
        assert body["transports"] == ["hls"]
        assert (
            body["media_session_id"]
            == media_session_id
        )
        assert (
            body["compatibility"]
            == "h264_transcode"
        )
        assert (
            body["compatibility_lease_id"]
            == str(lease_id)
        )
        assert (
            body["compatibility_acceleration"]
            == "cpu"
        )
        assert body["hls_url"].startswith(
            "/zlm/zero-nvr-compat/h264-"
        )
        assert "zn_exp=" in body["hls_url"]
        assert "zn_sig=" in body["hls_url"]

        source_url = str(
            captured["source_url"]
        )
        assert source_url.startswith(
            "rtsp://zlmediakit:554/zero-nvr/profile-"
        )
        assert "zn_sid=" in source_url
        assert "zn_sig=" in source_url
        assert "camera-secret" not in source_url
        assert "camera-token" not in source_url
        assert "10.0.0.10" not in source_url

        keepalive = client.post(
            (
                f"/api/v1/cameras/{camera_id}"
                f"/live/compatibility/{lease_id}"
                f"/keepalive?media_session_id={media_session_id}"
            )
        )
        assert keepalive.status_code == 204
        assert captured["touched"][0:2] == (
            str(lease_id),
            camera_id,
        )
        assert captured["touched"][2] == captured[
            "owner_user_id"
        ]

        released = client.delete(
            (
                f"/api/v1/cameras/{camera_id}"
                f"/live/compatibility/{lease_id}"
                f"?media_session_id={media_session_id}"
            )
        )
        assert released.status_code == 204
        assert captured["released"][0:2] == (
            str(lease_id),
            camera_id,
        )
        assert captured["released"][2] == captured[
            "owner_user_id"
        ]



def test_live_ice_servers_require_authorized_media_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    def fake_ensure(
        self,
        desired,
        *,
        wait_online_seconds=None,
    ):
        return [
            item.reference
            for item in desired
        ]

    monkeypatch.setattr(
        CameraMediaRuntimeService,
        "ensure_streams",
        fake_ensure,
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
                        "rtsp://camera.local/main"
                    ),
                },
                "secondary_stream": None,
            },
        )
        assert created.status_code == 201
        camera_id = created.json()["id"]

        descriptor = client.get(
            f"/api/v1/cameras/{camera_id}/live"
        )
        assert descriptor.status_code == 200
        media_session_id = descriptor.json()[
            "media_session_id"
        ]

        disabled = client.get(
            (
                f"/api/v1/cameras/{camera_id}"
                "/live/ice?media_session_id="
                f"{media_session_id}"
            )
        )
        assert disabled.status_code == 200
        assert disabled.json() == {
            "enabled": False,
            "ice_servers": [],
        }

        app.state.settings.turn_enabled = True
        app.state.settings.turn_public_host = (
            "relay.example.test"
        )
        app.state.settings.turn_port = 3478
        app.state.settings.turn_shared_secret = (
            SecretStr("t" * 40)
        )
        app.state.settings.turn_credential_ttl_seconds = 600
        monkeypatch.setattr(
            "app.modules.cameras.turn.time.time",
            lambda: 1_000,
        )
        tuning = client.patch(
            "/api/v1/system/settings",
            json={
                "runtime": {
                    "turn_credential_ttl_seconds": 120,
                }
            },
        )
        assert tuning.status_code == 200

        descriptor_with_turn = client.get(
            f"/api/v1/cameras/{camera_id}/live"
        )
        assert descriptor_with_turn.status_code == 200
        turn_descriptor = descriptor_with_turn.json()
        assert turn_descriptor["ice_error"] is None
        assert len(turn_descriptor["ice_servers"]) == 1
        descriptor_server = turn_descriptor["ice_servers"][0]
        assert descriptor_server["urls"] == [
            (
                "turn:relay.example.test:3478"
                "?transport=udp"
            ),
            (
                "turn:relay.example.test:3478"
                "?transport=tcp"
            ),
        ]
        assert descriptor_server["username"].startswith("1120:")
        assert descriptor_server["credential"]
        assert "t" * 40 not in descriptor_with_turn.text

        enabled = client.get(
            (
                f"/api/v1/cameras/{camera_id}"
                "/live/ice?media_session_id="
                f"{media_session_id}"
            )
        )
        assert enabled.status_code == 200
        body = enabled.json()
        assert body["enabled"] is True
        assert len(body["ice_servers"]) == 1
        server = body["ice_servers"][0]
        assert server["urls"] == [
            (
                "turn:relay.example.test:3478"
                "?transport=udp"
            ),
            (
                "turn:relay.example.test:3478"
                "?transport=tcp"
            ),
        ]
        assert server["username"].startswith(
            "1120:"
        )
        assert server["credential"]
        assert server["expires_at"].startswith(
            "1970-01-01T00:18:40"
        )
        assert "t" * 40 not in enabled.text

        missing = client.get(
            (
                f"/api/v1/cameras/{camera_id}"
                "/live/ice?media_session_id="
                f"{uuid.uuid4()}"
            )
        )
        assert missing.status_code == 404
        assert (
            missing.json()["error"]["code"]
            == "media_session_not_found"
        )
