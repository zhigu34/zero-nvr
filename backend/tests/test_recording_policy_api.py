from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.modules.recordings.api as recording_api
from app.core.config import Settings
from app.core.db import Base
from app.core.errors import ApiError
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import Role
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingPolicy
from app.modules.recordings.runtime import RecorderReconcileResult
from app.modules.storage.models import StorageTarget


ADMIN_PASSWORD = "correct-horse-battery-staple"
VIEWER_PASSWORD = "viewer-correct-horse-battery"


class FakeRecordingTasks:
    def __init__(self) -> None:
        self.scheduled = []

    def schedule_policy(
        self,
        *,
        policy_id,
        policy_version,
        eta,
    ) -> None:
        self.scheduled.append(
            {
                "policy_id": policy_id,
                "policy_version": policy_version,
                "eta": eta,
            }
        )

    def reconcile_camera(self, _camera_id) -> None:
        return None

    def finalized_prebuffer_fragment(self, _fragment) -> None:
        return None


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="recording-policy-api-test-secret-key-32-bytes",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'policy-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
        session_cookie_secure=False,
    )
    settings.prebuffer_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    app.state.recording_tasks = FakeRecordingTasks()
    return app


def setup_admin(client: TestClient) -> str:
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
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    token = client.cookies.get("zero_nvr_session")
    assert token
    return token


def seed_camera_and_storage(app) -> uuid.UUID:
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
        session.add(
            StorageTarget(
                name="Local Recording",
                type="local",
                role="recording",
                enabled=True,
                config_json={
                    "path": "/recordings",
                    "default_recording": True,
                },
            )
        )
        session.commit()
        return camera.id


def patch_runtime_success(monkeypatch):
    calls: list[dict[str, object]] = []

    def ensure_streams(self, desired):
        calls.append(
            {
                "kind": "media",
                "profiles": [str(item.profile_id) for item in desired],
            }
        )
        return []

    def reconcile(self, desired, *, force_reconfigure=False):
        calls.append(
            {
                "kind": "recorder",
                "mode": desired.mode if desired else "off",
                "force": force_reconfigure,
            }
        )
        return RecorderReconcileResult(
            desired_mode=desired.mode if desired else "off",
            observed_recording=bool(
                desired is not None and desired.mode != "off"
            ),
            changed=True,
            assumed_existing_mode=False,
        )

    monkeypatch.setattr(
        recording_api.CameraMediaRuntimeService,
        "ensure_streams",
        ensure_streams,
    )
    monkeypatch.setattr(
        recording_api.RecordingRuntimeService,
        "reconcile",
        reconcile,
    )
    return calls


def continuous_payload() -> dict[str, object]:
    return {
        "baseline_mode": "continuous",
        "schedule": {},
        "schedule_timezone": None,
        "event_recording_enabled": False,
        "event_filter": {},
        "segment_target_seconds": 300,
        "pre_roll_seconds": 10,
        "post_roll_seconds": 10,
        "storage_target_id": None,
        "retention_policy_id": None,
        "enabled": True,
    }


def test_recording_policy_put_get_audit_and_runtime(tmp_path: Path, monkeypatch) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        admin_token = setup_admin(client)
        camera_id = seed_camera_and_storage(app)
        calls = patch_runtime_success(monkeypatch)

        missing = client.get(
            f"/api/v1/cameras/{camera_id}/recording-policy"
        )
        assert missing.status_code == 404
        assert (
            missing.json()["error"]["code"]
            == "recording_policy_not_configured"
        )

        saved = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["baseline_mode"] == "continuous"
        assert body["event_recording_enabled"] is False
        assert body["runtime"] == {
            "desired_mode": "persistent",
            "recording": True,
            "changed": True,
            "assumed_existing_mode": False,
        }
        assert calls[0]["kind"] == "media"
        assert calls[1] == {
            "kind": "recorder",
            "mode": "persistent",
            "force": True,
        }

        fetched = client.get(
            f"/api/v1/cameras/{camera_id}/recording-policy"
        )
        assert fetched.status_code == 200
        assert fetched.json()["runtime"] is None
        assert fetched.json()["baseline_mode"] == "continuous"

        # A no-op policy PUT must not force recorder path reconfiguration.
        calls.clear()
        repeated = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert repeated.status_code == 200
        assert calls[1]["force"] is False

        # Viewer can read the policy but cannot mutate it.
        with app.state.database.session() as session:
            viewer_role = session.scalar(
                select(Role).where(Role.name == "Viewer")
            )
            assert viewer_role is not None
            viewer_role_id = viewer_role.id

        viewer = client.post(
            "/api/v1/users",
            json={
                "username": "viewer",
                "display_name": "Viewer",
                "password": VIEWER_PASSWORD,
                "role_ids": [str(viewer_role_id)],
            },
        )
        assert viewer.status_code == 201

        client.post("/api/v1/auth/logout")
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": VIEWER_PASSWORD},
        )
        assert login.status_code == 200

        readable = client.get(
            f"/api/v1/cameras/{camera_id}/recording-policy"
        )
        assert readable.status_code == 200

        denied = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "permission_denied"

    with app.state.database.session() as session:
        actions = set(
            session.scalars(select(AuditEvent.action)).all()
        )
    assert "recording_policy.update" in actions


def test_event_only_policy_plans_prebuffer_mode(tmp_path: Path, monkeypatch) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)
        calls = patch_runtime_success(monkeypatch)

        payload = continuous_payload()
        payload.update(
            {
                "baseline_mode": "disabled",
                "event_recording_enabled": True,
                "event_filter": {"labels": ["person"]},
                "pre_roll_seconds": 10,
                "post_roll_seconds": 15,
            }
        )

        response = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=payload,
        )
        assert response.status_code == 200
        assert response.json()["runtime"]["desired_mode"] == "prebuffer"
        assert calls[-1]["mode"] == "prebuffer"


def test_policy_runtime_failure_does_not_roll_back_canonical_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    def ensure_streams(self, desired):
        return []

    def fail_reconcile(self, desired, *, force_reconfigure=False):
        raise ApiError(
            status_code=503,
            code="recording_start_failed",
            message="ZLMediaKit did not start recording.",
        )

    monkeypatch.setattr(
        recording_api.CameraMediaRuntimeService,
        "ensure_streams",
        ensure_streams,
    )
    monkeypatch.setattr(
        recording_api.RecordingRuntimeService,
        "reconcile",
        fail_reconcile,
    )

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)

        response = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "recording_start_failed"
        assert response.json()["error"]["details"]["policy_persisted"] is True

        fetched = client.get(
            f"/api/v1/cameras/{camera_id}/recording-policy"
        )
        assert fetched.status_code == 200
        assert fetched.json()["baseline_mode"] == "continuous"

    with app.state.database.session() as session:
        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )
        assert policy is not None
        assert policy.baseline_mode == "continuous"



def test_schedule_policy_put_queues_only_next_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)
        patch_runtime_success(monkeypatch)

        payload = continuous_payload()
        payload.update(
            {
                "baseline_mode": "schedule",
                "schedule": {
                    "weekly": [
                        {
                            "days": [0, 1, 2, 3, 4, 5, 6],
                            "start": "08:00",
                            "end": "20:00",
                        }
                    ]
                },
                "schedule_timezone": "UTC",
            }
        )

        response = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=payload,
        )
        assert response.status_code == 200

    tasks = app.state.recording_tasks
    assert len(tasks.scheduled) == 1
    scheduled = tasks.scheduled[0]
    assert scheduled["policy_id"] == uuid.UUID(
        response.json()["id"]
    )
    assert scheduled["policy_version"]
    assert scheduled["eta"].tzinfo is not None
