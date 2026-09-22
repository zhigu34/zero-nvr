from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
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
from app.integrations.zlm import ZlmIntegrationError
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
CAMERA_PASSWORD_NEW = "new p@ss word"

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


PROBED_URIS: list[str] = []


class FakeZlmAdapter:
    def __init__(
        self,
        _settings,
    ) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(
        self,
        *_exc,
    ) -> None:
        return None

    def probe_rtsp_source(
        self,
        source_url: str,
    ):
        PROBED_URIS.append(
            source_url
        )
        return object()


@pytest.fixture(autouse=True)
def fake_zlm_adapter(
    monkeypatch,
):
    PROBED_URIS.clear()
    monkeypatch.setattr(
        camera_api,
        "ZlmAdapter",
        FakeZlmAdapter,
    )


class FakeRecordingTasks:
    def __init__(self) -> None:
        self.runtime_reconciles: list[
            tuple[uuid.UUID, bool]
        ] = []

    def reconcile_runtime(
        self,
        camera_id: uuid.UUID,
        *,
        restart_streams: bool = False,
    ) -> None:
        self.runtime_reconciles.append(
            (camera_id, restart_streams)
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
    app.state.recording_tasks = FakeRecordingTasks()
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
        assert {
            camera["time_sync_mode"]
            for camera in body["cameras"]
        } == {"monitor"}
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
        assert {
            item["selection_mode"]
            for item in first["bindings"]
        } == {"auto"}
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

        probes_before_reconfigure = len(
            PROBED_URIS
        )
        repeated = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.20",
                "port": 80,
                "username": CAMERA_USERNAME,
                "password": CAMERA_PASSWORD,
                "name": "Warehouse Duplicate",
                "profile_tokens": ["sub-a"],
            },
        )
        assert repeated.status_code == 201
        assert repeated.json()["reconfigured"] is True
        assert repeated.json()["device_id"] == body["device_id"]
        reconfigure_probes = PROBED_URIS[
            probes_before_reconfigure:
        ]
        assert len(
            reconfigure_probes
        ) == 3
        assert {
            uri.split("?", 1)[0]
            for uri in reconfigure_probes
        } == {
            (
                "rtsp://cam%20user:p%40ss%20word@"
                "192.168.70.20:554/channel/a/main"
            ),
            (
                "rtsp://cam%20user:p%40ss%20word@"
                "192.168.70.20:554/channel/a/sub"
            ),
            (
                "rtsp://cam%20user:p%40ss%20word@"
                "192.168.70.20:554/channel/b/main"
            ),
        }

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
        assert PROBED_URIS == [
            (
                "rtsp://admin:secret-password@"
                "192.168.70.20:554/channel/a/sub"
                "?token=sub-a-secret"
            )
        ]


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
        assert PROBED_URIS == []

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



def test_onvif_import_rejects_failed_zlm_stream_verification_without_persistence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    class FakeOnvifAdapter:
        def __init__(
            self,
            _settings,
        ) -> None:
            pass

        async def inspect_device(
            self,
            **_kwargs,
        ):
            return inspection()

    class FailingZlmAdapter(
        FakeZlmAdapter
    ):
        def probe_rtsp_source(
            self,
            source_url: str,
        ):
            PROBED_URIS.append(
                source_url
            )
            raise ZlmIntegrationError(
                "camera_stream_probe_failed",
                "Camera stream verification failed.",
                status_code=422,
            )

    monkeypatch.setattr(
        camera_api,
        "OnvifAdapter",
        FakeOnvifAdapter,
    )
    monkeypatch.setattr(
        camera_api,
        "ZlmAdapter",
        FailingZlmAdapter,
    )

    with TestClient(app) as client:
        setup_admin(client)

        response = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.20",
                "port": 80,
                "username": CAMERA_USERNAME,
                "password": CAMERA_PASSWORD,
            },
        )
        assert response.status_code == 422
        assert (
            response.json()["error"]["code"]
            == "camera_stream_probe_failed"
        )
        assert (
            response.json()["error"]["details"][
                "profile_token"
            ]
            == "main-a"
        )

    assert len(PROBED_URIS) == 1
    assert (
        "cam%20user:p%40ss%20word@"
        in PROBED_URIS[0]
    )

    with app.state.database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(
                Device
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(
                Camera
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(
                SecretRecord
            )
        ) == 0


def _inspection_at(host: str) -> OnvifInspection:
    source = inspection()
    profiles = []
    for item in source.profiles:
        assert item.stream_uri is not None
        profiles.append(
            OnvifProfileProbe(
                token=item.token,
                name=item.name,
                video_source_token=item.video_source_token,
                codec=item.codec,
                width=item.width,
                height=item.height,
                fps=item.fps,
                bitrate_kbps=item.bitrate_kbps,
                gop_seconds=item.gop_seconds,
                audio_codec=item.audio_codec,
                has_audio=item.has_audio,
                stream_uri_available=True,
                stream_uri=item.stream_uri.replace(
                    "192.168.70.20",
                    host,
                ),
            )
        )
    return OnvifInspection(
        device=source.device,
        capabilities=source.capabilities,
        profiles=tuple(profiles),
    )


def test_onvif_reimport_same_hardware_refreshes_address_without_replacing_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    class FakeOnvifAdapter:
        def __init__(self, _settings) -> None:
            pass

        async def inspect_device(self, **kwargs):
            return _inspection_at(
                str(kwargs["host"])
            )

    monkeypatch.setattr(
        camera_api,
        "OnvifAdapter",
        FakeOnvifAdapter,
    )

    with TestClient(app) as client:
        setup_admin(client)
        first = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.20",
                "port": 80,
                "username": CAMERA_USERNAME,
                "password": CAMERA_PASSWORD,
                "name": "Warehouse",
            },
        )
        assert first.status_code == 201
        first_body = first.json()
        assert first_body["reconfigured"] is False
        device_id = first_body["device_id"]
        camera_ids = [
            item["id"]
            for item in first_body["cameras"]
        ]
        profile_ids = {
            stream["adapter_profile_key"]: stream["id"]
            for camera in first_body["cameras"]
            for stream in camera["streams"]
        }

        with app.state.database.session() as session:
            credential = session.scalar(
                select(DeviceCredential).where(
                    DeviceCredential.device_id
                    == uuid.UUID(device_id),
                    DeviceCredential.kind == "onvif",
                )
            )
            assert credential is not None
            old_credential_ref = (
                credential.secret_ref
            )
            old_stream_refs = {
                profile.adapter_profile_key: (
                    profile.stream_uri_ref
                )
                for profile in session.scalars(
                    select(CameraStreamProfile).where(
                        CameraStreamProfile.id.in_(
                            [
                                uuid.UUID(value)
                                for value in profile_ids.values()
                            ]
                        )
                    )
                )
            }
            assert all(
                value is not None
                for value in old_stream_refs.values()
            )

        refreshed = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.99",
                "port": 8080,
                "username": "new user",
                "password": CAMERA_PASSWORD_NEW,
                "name": "Ignored Rename",
            },
        )
        assert refreshed.status_code == 201
        body = refreshed.json()
        assert body["reconfigured"] is True
        assert body["device_id"] == device_id
        assert [
            item["id"]
            for item in body["cameras"]
        ] == camera_ids
        assert {
            stream["adapter_profile_key"]: stream["id"]
            for camera in body["cameras"]
            for stream in camera["streams"]
        } == profile_ids

    with app.state.database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(Device)
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

        endpoint = session.scalar(
            select(DeviceEndpoint)
        )
        assert endpoint is not None
        assert endpoint.host == "192.168.70.99"
        assert endpoint.port == 8080

        credential = session.scalar(
            select(DeviceCredential).where(
                DeviceCredential.device_id
                == uuid.UUID(device_id),
                DeviceCredential.kind == "onvif",
            )
        )
        assert credential is not None
        assert credential.secret_ref != old_credential_ref
        assert (
            session.get(
                SecretRecord,
                old_credential_ref,
            )
            is None
        )

        current_profiles = list(
            session.scalars(
                select(CameraStreamProfile).where(
                    CameraStreamProfile.id.in_(
                        [
                            uuid.UUID(value)
                            for value in profile_ids.values()
                        ]
                    )
                )
            )
        )
        for profile in current_profiles:
            old_ref = old_stream_refs[
                profile.adapter_profile_key
            ]
            assert profile.stream_uri_ref is not None
            assert profile.stream_uri_ref != old_ref
            assert session.get(
                SecretRecord,
                old_ref,
            ) is None

        main_profile = session.scalar(
            select(CameraStreamProfile).where(
                CameraStreamProfile.adapter_profile_key
                == "main-a"
            )
        )
        assert main_profile is not None
        resolved = CameraService(
            app.state.settings
        ).resolve_stream_uri(
            session,
            main_profile,
        )
        assert "192.168.70.99" in resolved
        assert "new%20user" in resolved
        assert "new%20p%40ss%20word" in resolved
        assert "192.168.70.20" not in resolved

        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action
                    == "camera.onvif.reconfigure"
                )
            )
        )
        assert len(audits) == 1
        assert audits[0].metadata_json["reconfigured"] is True

    assert set(
        app.state.recording_tasks.runtime_reconciles
    ) == {
        (uuid.UUID(camera_id), True)
        for camera_id in camera_ids
    }


def test_onvif_reconfigure_rejects_topology_change_before_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    changed = False

    class FakeOnvifAdapter:
        def __init__(self, _settings) -> None:
            pass

        async def inspect_device(self, **kwargs):
            value = _inspection_at(
                str(kwargs["host"])
            )
            if not changed:
                return value
            return OnvifInspection(
                device=value.device,
                capabilities=value.capabilities,
                profiles=tuple(
                    item
                    for item in value.profiles
                    if item.token != "sub-a"
                ),
            )

    monkeypatch.setattr(
        camera_api,
        "OnvifAdapter",
        FakeOnvifAdapter,
    )

    with TestClient(app) as client:
        setup_admin(client)
        created = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.20",
                "port": 80,
                "username": CAMERA_USERNAME,
                "password": CAMERA_PASSWORD,
            },
        )
        assert created.status_code == 201

        changed = True
        rejected = client.post(
            "/api/v1/cameras/onvif/import",
            json={
                "host": "192.168.70.77",
                "port": 80,
                "username": "new",
                "password": CAMERA_PASSWORD_NEW,
            },
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == (
            "onvif_device_topology_changed"
        )

    with app.state.database.session() as session:
        endpoint = session.scalar(
            select(DeviceEndpoint)
        )
        assert endpoint is not None
        assert endpoint.host == "192.168.70.20"
