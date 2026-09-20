from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.modules.cameras.api as camera_api
from app.core.config import Settings
from app.core.db import Base
from app.integrations.onvif import (
    OnvifDeviceInfo,
    OnvifInspection,
    OnvifProfileProbe,
)
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import SecretRecord
from app.modules.cameras.models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    DeviceCredential,
    DeviceEndpoint,
    DiscoveryCandidate,
    DiscoverySession,
)
from app.modules.cameras.service import CameraService


ADMIN_PASSWORD = "correct-horse-battery-staple"
CAMERA_USERNAME = "cam user"
CAMERA_PASSWORD = "p@ss word"

URI_MAIN_A = (
    "rtsp://192.168.70.20:554/channel/a/main"
    "?token=main-a-secret"
)
URI_SUB_A = (
    "rtsp://192.168.70.20:554/channel/a/sub"
    "?token=sub-a-secret"
)
URI_MAIN_B = (
    "rtsp://192.168.70.20:554/channel/b/main"
    "?token=main-b-secret"
)


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="onvif-import-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'onvif-import.db'}",
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


def inspection() -> OnvifInspection:
    return OnvifInspection(
        device=OnvifDeviceInfo(
            manufacturer="Acme",
            model="NVR-2CH",
            firmware_version="5.0.0",
            serial_number="SERIAL-2CH",
            hardware_id="HW-2CH",
        ),
        capabilities=("Media", "PTZ"),
        profiles=(
            OnvifProfileProbe(
                token="main-a",
                name="Channel A Main",
                video_source_token="source-a",
                codec="h265",
                width=3840,
                height=2160,
                fps=25.0,
                bitrate_kbps=8192,
                gop_seconds=2.0,
                audio_codec="aac",
                has_audio=True,
                stream_uri_available=True,
                stream_uri=URI_MAIN_A,
            ),
            OnvifProfileProbe(
                token="sub-a",
                name="Channel A Sub",
                video_source_token="source-a",
                codec="h264",
                width=640,
                height=360,
                fps=10.0,
                bitrate_kbps=512,
                gop_seconds=1.0,
                audio_codec=None,
                has_audio=False,
                stream_uri_available=True,
                stream_uri=URI_SUB_A,
            ),
            OnvifProfileProbe(
                token="main-b",
                name="Channel B Main",
                video_source_token="source-b",
                codec="h264",
                width=1920,
                height=1080,
                fps=20.0,
                bitrate_kbps=4096,
                gop_seconds=2.0,
                audio_codec=None,
                has_audio=False,
                stream_uri_available=True,
                stream_uri=URI_MAIN_B,
            ),
        ),
    )


def seed_discovery_candidate(app) -> uuid.UUID:
    with app.state.database.session() as session:
        discovery = DiscoverySession(
            method="onvif_ws_discovery",
            status="completed",
        )
        session.add(discovery)
        session.flush()
        candidate = DiscoveryCandidate(
            discovery_session_id=discovery.id,
            candidate_key="urn:uuid:hw-2ch",
            host="192.168.70.20",
            device_identity={"epr": "urn:uuid:hw-2ch"},
            display_info={"name": "Warehouse NVR"},
            state="discovered",
            metadata_json={
                "port": 80,
                "device_service_url": (
                    "http://192.168.70.20/onvif/device_service"
                ),
                "xaddrs": [
                    "http://192.168.70.20/onvif/device_service"
                ],
                "scopes": [],
            },
        )
        session.add(candidate)
        session.commit()
        return candidate.id


def test_onvif_import_creates_device_multichannel_cameras_and_runtime_auth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    adapter_calls: list[dict[str, object]] = []

    class FakeOnvifAdapter:
        def __init__(self, _settings) -> None:
            pass

        async def inspect_device(self, **kwargs):
            adapter_calls.append(kwargs)
            return inspection()

    monkeypatch.setattr(camera_api, "OnvifAdapter", FakeOnvifAdapter)

    with TestClient(app) as client:
        setup_admin(client)
        candidate_id = seed_discovery_candidate(app)

        response = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.20",
                "port": 80,
                "username": CAMERA_USERNAME,
                "password": CAMERA_PASSWORD,
                "name": "Warehouse",
                "location": "Loading Bay",
                "storage_label": "critical",
                "discovery_candidate_id": str(candidate_id),
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert uuid.UUID(body["device_id"])
        assert [camera["name"] for camera in body["cameras"]] == [
            "Warehouse 1",
            "Warehouse 2",
        ]
        assert all(
            camera["adapter_type"] == "onvif"
            for camera in body["cameras"]
        )

        serialized = json.dumps(body)
        assert CAMERA_PASSWORD not in serialized
        assert CAMERA_USERNAME not in serialized
        assert "rtsp://" not in serialized
        assert "main-a-secret" not in serialized
        assert "sub-a-secret" not in serialized
        assert "main-b-secret" not in serialized

        first = body["cameras"][0]
        profiles = {
            item["adapter_profile_key"]: item
            for item in first["streams"]
        }
        assert set(profiles) == {"main-a", "sub-a"}
        assert profiles["main-a"]["width"] == 3840
        assert profiles["sub-a"]["width"] == 640

        bindings = {
            item["purpose"]: item["stream_profile_id"]
            for item in first["bindings"]
        }
        assert bindings["RECORD"] == profiles["main-a"]["id"]
        assert bindings["LIVE_HIGH"] == profiles["main-a"]["id"]
        assert bindings["SNAPSHOT"] == profiles["main-a"]["id"]
        assert bindings["AUDIO"] == profiles["main-a"]["id"]
        assert bindings["LIVE_LOW"] == profiles["sub-a"]["id"]
        assert bindings["AI_DETECT"] == profiles["sub-a"]["id"]

        assert adapter_calls == [
            {
                "host": "192.168.70.20",
                "port": 80,
                "username": CAMERA_USERNAME,
                "password": CAMERA_PASSWORD,
            }
        ]

        duplicate = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.20",
                "port": 80,
                "username": CAMERA_USERNAME,
                "password": CAMERA_PASSWORD,
                "name": "Warehouse Duplicate",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == (
            "onvif_device_already_exists"
        )

    with app.state.database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(Device)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(DeviceEndpoint)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(DeviceCredential)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(Camera)
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(CameraStreamProfile)
        ) == 3
        assert session.scalar(
            select(func.count()).select_from(SecretRecord)
        ) == 4

        candidate = session.get(DiscoveryCandidate, candidate_id)
        assert candidate is not None
        assert candidate.state == "imported"

        secret_rows = list(session.scalars(select(SecretRecord)))
        assert all(
            CAMERA_PASSWORD.encode() not in row.encrypted_payload
            and URI_MAIN_A.encode() not in row.encrypted_payload
            and URI_SUB_A.encode() not in row.encrypted_payload
            and URI_MAIN_B.encode() not in row.encrypted_payload
            for row in secret_rows
        )

        main_profile = session.scalar(
            select(CameraStreamProfile).where(
                CameraStreamProfile.adapter_profile_key == "main-a"
            )
        )
        assert main_profile is not None

        resolved = CameraService(
            app.state.settings
        ).resolve_stream_uri(session, main_profile)
        assert resolved == (
            "rtsp://cam%20user:p%40ss%20word@"
            "192.168.70.20:554/channel/a/main"
            "?token=main-a-secret"
        )

        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "camera.onvif.import"
                )
            )
        )
        assert len(audits) == 1
        assert audits[0].metadata_json["camera_count"] == 2
        assert audits[0].metadata_json["profile_count"] == 3


def test_onvif_import_can_select_profile_subset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    class FakeOnvifAdapter:
        def __init__(self, _settings) -> None:
            pass

        async def inspect_device(self, **_kwargs):
            return inspection()

    monkeypatch.setattr(camera_api, "OnvifAdapter", FakeOnvifAdapter)

    with TestClient(app) as client:
        setup_admin(client)

        response = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.30",
                "port": 80,
                "username": "admin",
                "password": "secret-password",
                "name": "Selected",
                "profile_tokens": ["sub-a"],
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert len(body["cameras"]) == 1
        assert [
            stream["adapter_profile_key"]
            for stream in body["cameras"][0]["streams"]
        ] == ["sub-a"]


def test_onvif_import_rejects_unknown_profile_without_partial_persistence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    class FakeOnvifAdapter:
        def __init__(self, _settings) -> None:
            pass

        async def inspect_device(self, **_kwargs):
            return inspection()

    monkeypatch.setattr(camera_api, "OnvifAdapter", FakeOnvifAdapter)

    with TestClient(app) as client:
        setup_admin(client)

        response = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.40",
                "port": 80,
                "username": "admin",
                "password": "secret-password",
                "profile_tokens": ["does-not-exist"],
            },
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == (
            "invalid_onvif_profile_tokens"
        )

    with app.state.database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(Device)
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(Camera)
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(SecretRecord)
        ) == 0
