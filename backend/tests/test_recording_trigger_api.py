from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingPolicy, RecordingTrigger
from app.modules.storage.models import StorageTarget


ADMIN_PASSWORD = "correct-horse-battery-staple"


class FakeDispatcher:
    def __init__(self) -> None:
        self.camera_ids: list[uuid.UUID] = []

    def reconcile_camera(self, camera_id: uuid.UUID) -> None:
        self.camera_ids.append(camera_id)

    def finalized_prebuffer_fragment(self, _fragment) -> None:
        return None


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="trigger-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'trigger-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    app.state.recording_tasks = FakeDispatcher()
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


def seed_event_camera(app) -> uuid.UUID:
    with app.state.database.session() as session:
        camera = CameraService(
            app.state.settings
        ).create_manual_rtsp_camera(
            session,
            name="Front Door",
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url="rtsp://camera.local/main",
            secondary_name=None,
            secondary_url=None,
        )
        target = StorageTarget(
            name="Local Recording",
            type="local",
            role="recording",
            enabled=True,
            config_json={
                "path": "/recordings",
                "default_recording": True,
            },
        )
        session.add(target)
        session.flush()
        session.add(
            RecordingPolicy(
                camera_id=camera.id,
                baseline_mode="disabled",
                event_recording_enabled=True,
                storage_target_id=target.id,
                pre_roll_seconds=10,
                post_roll_seconds=15,
                enabled=True,
            )
        )
        session.commit()
        return camera.id


def test_manual_trigger_is_idempotent_and_stop_adds_postroll(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_event_camera(app)

        first = client.post(
            f"/api/v1/cameras/{camera_id}/recording-triggers",
            headers={"Idempotency-Key": "doorbell-1"},
            json={"reason": "doorbell"},
        )
        assert first.status_code == 201
        first_body = first.json()
        assert first_body["state"] == "ACTIVE"
        assert first_body["planned_end_at"] is None
        assert first_body["pre_roll_seconds"] == 10
        assert first_body["post_roll_seconds"] == 15

        retry = client.post(
            f"/api/v1/cameras/{camera_id}/recording-triggers",
            headers={"Idempotency-Key": "doorbell-1"},
            json={"reason": "doorbell"},
        )
        assert retry.status_code == 201
        assert retry.json()["id"] == first_body["id"]

        listed = client.get(
            f"/api/v1/cameras/{camera_id}/recording-triggers"
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        stopped = client.post(
            f"/api/v1/recording-triggers/{first_body['id']}/stop"
        )
        assert stopped.status_code == 200
        stopped_body = stopped.json()
        assert stopped_body["state"] == "COMPLETED"
        assert stopped_body["planned_end_at"] is not None

        stopped_again = client.post(
            f"/api/v1/recording-triggers/{first_body['id']}/stop"
        )
        assert stopped_again.status_code == 200
        assert (
            stopped_again.json()["planned_end_at"]
            == stopped_body["planned_end_at"]
        )

    with app.state.database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(RecordingTrigger)
        ) == 1

    dispatcher = app.state.recording_tasks
    assert dispatcher.camera_ids.count(camera_id) >= 3


def test_trigger_requires_event_recording_enabled(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_event_camera(app)

        with app.state.database.session() as session:
            policy = session.scalar(
                select(RecordingPolicy).where(
                    RecordingPolicy.camera_id == camera_id
                )
            )
            assert policy is not None
            policy.event_recording_enabled = False
            session.commit()

        response = client.post(
            f"/api/v1/cameras/{camera_id}/recording-triggers",
            json={},
        )
        assert response.status_code == 409
        assert (
            response.json()["error"]["code"]
            == "event_recording_not_enabled"
        )
