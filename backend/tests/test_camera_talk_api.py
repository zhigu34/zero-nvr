from __future__ import annotations

from pathlib import Path
import uuid

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db.base import Base
from app.core.security import SecretStore
from app.main import create_app
from app.modules.auth.models import SecretRecord
from app.modules.cameras.models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
)
from app.modules.cameras.talk import (
    CameraTalkConnection,
    TalkBackendHandle,
)


ADMIN_PASSWORD = "Talk-test-admin-password-123!"


class FakeTalkBackend:
    name = "test_backchannel"
    modes = ("push_to_talk",)

    def __init__(self) -> None:
        self.started: list[uuid.UUID] = []
        self.stopped: list[uuid.UUID] = []

    def available(self) -> bool:
        return True

    def supports(
        self,
        connection: CameraTalkConnection,
    ) -> bool:
        return True

    def start(
        self,
        *,
        talk_session_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        connection: CameraTalkConnection,
        mode: str,
    ) -> TalkBackendHandle:
        self.started.append(
            talk_session_id
        )
        return TalkBackendHandle(
            descriptor={
                "transport": "test",
                "mode": mode,
            },
            state=talk_session_id,
        )

    def stop(
        self,
        handle: TalkBackendHandle,
    ) -> None:
        assert isinstance(
            handle.state,
            uuid.UUID,
        )
        self.stopped.append(
            handle.state
        )


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key=(
            "camera-talk-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'talk.db'}"
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


def setup_admin(
    client: TestClient,
) -> None:
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


def seed_talk_camera(app) -> uuid.UUID:
    store = SecretStore(
        app.state.settings
    )
    with app.state.database.session() as session:
        device = Device(
            name="Talk Camera",
            adapter_type="onvif",
            enabled=True,
            capabilities_json={
                "onvif_services": [
                    "Media",
                ],
            },
        )
        session.add(device)
        session.flush()

        camera = Camera(
            device_id=device.id,
            channel_key="source-1",
            name="Talk Camera",
            enabled=True,
        )
        session.add(camera)
        session.flush()

        encrypted = store.encrypt_json(
            {
                "uri": (
                    "rtsp://camera-user:"
                    "camera-password@"
                    "192.0.2.20/main"
                )
            }
        )
        secret = SecretRecord(
            kind="rtsp_uri",
            owner_type=(
                "camera_stream_profile"
            ),
            owner_id=uuid.uuid4(),
            key_id=encrypted.key_id,
            encrypted_payload=(
                encrypted.ciphertext
            ),
            version=encrypted.version,
        )
        session.add(secret)
        session.flush()

        profile = CameraStreamProfile(
            camera_id=camera.id,
            adapter_profile_key="main",
            video_source_key="source-1",
            name="Main",
            codec="h264",
            audio_codec="aac",
            has_audio=True,
            stream_uri_ref=secret.id,
            status="available",
            metadata_json={
                "onvif_audio_backchannel": True,
            },
        )
        session.add(profile)
        session.flush()
        secret.owner_id = profile.id

        session.add(
            CameraStreamBinding(
                camera_id=camera.id,
                purpose="AUDIO",
                stream_profile_id=profile.id,
                selection_mode="auto",
            )
        )
        session.commit()
        return camera.id


def test_talk_capability_and_single_talker_session_api(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    backend = FakeTalkBackend()
    app.state.talk_backend = backend

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_talk_camera(
            app
        )

        cameras = client.get(
            "/api/v1/cameras"
        )
        assert cameras.status_code == 200
        camera = next(
            item
            for item in cameras.json()
            if item["id"]
            == str(camera_id)
        )
        assert (
            camera["talk_capable"]
            is True
        )

        capability = client.get(
            (
                f"/api/v1/cameras/"
                f"{camera_id}/talk"
            )
        )
        assert capability.status_code == 200
        assert capability.json() == {
            "capable": True,
            "ready": True,
            "backend": "test_backchannel",
            "modes": [
                "push_to_talk",
            ],
        }

        started = client.post(
            (
                f"/api/v1/cameras/"
                f"{camera_id}/talk/session"
            ),
            json={
                "mode": "push_to_talk",
            },
        )
        assert started.status_code == 201
        body = started.json()
        talk_session_id = body["id"]
        assert body["camera_id"] == (
            str(camera_id)
        )
        assert body["backend"] == (
            "test_backchannel"
        )
        assert body["descriptor"] == {
            "transport": "test",
            "mode": "push_to_talk",
        }

        busy = client.post(
            (
                f"/api/v1/cameras/"
                f"{camera_id}/talk/session"
            ),
            json={
                "mode": "push_to_talk",
            },
        )
        assert busy.status_code == 409
        assert (
            busy.json()["error"]["code"]
            == "camera_talk_busy"
        )

        keepalive = client.post(
            (
                f"/api/v1/cameras/"
                f"{camera_id}/talk/session/"
                f"{talk_session_id}/keepalive"
            )
        )
        assert keepalive.status_code == 204

        stopped = client.delete(
            (
                f"/api/v1/cameras/"
                f"{camera_id}/talk/session/"
                f"{talk_session_id}"
            )
        )
        assert stopped.status_code == 204
        assert backend.stopped == [
            uuid.UUID(
                talk_session_id
            )
        ]

        gone = client.post(
            (
                f"/api/v1/cameras/"
                f"{camera_id}/talk/session/"
                f"{talk_session_id}/keepalive"
            )
        )
        assert gone.status_code == 404


def test_talk_session_stays_unavailable_without_transport_backend(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_talk_camera(
            app
        )

        capability = client.get(
            (
                f"/api/v1/cameras/"
                f"{camera_id}/talk"
            )
        )
        assert capability.status_code == 200
        assert capability.json() == {
            "capable": True,
            "ready": False,
            "backend": None,
            "modes": [],
        }

        started = client.post(
            (
                f"/api/v1/cameras/"
                f"{camera_id}/talk/session"
            ),
            json={
                "mode": "push_to_talk",
            },
        )
        assert started.status_code == 409
        assert (
            started.json()["error"]["code"]
            == (
                "camera_talk_backend_"
                "unavailable"
            )
        )
