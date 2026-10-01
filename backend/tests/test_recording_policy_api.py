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
from app.integrations.zlm import ZlmIntegrationError
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
        self.runtime_calls = []

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

    def reconcile_runtime(
        self,
        camera_id,
        *,
        restart_streams: bool = False,
        force_reconfigure: bool = False,
    ) -> None:
        self.runtime_calls.append(
            (
                camera_id,
                restart_streams,
                force_reconfigure,
            )
        )

    def finalized_prebuffer_fragment(self, _fragment) -> None:
        return None


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="recording-policy-api-test-secret-key-32-bytes",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'policy-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=tmp_path / "recordings",
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
    recording_root = (
        app.state.settings.recordings_dir
    )
    recording_root.mkdir(
        parents=True,
        exist_ok=True,
    )
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
                    "path": str(recording_root),
                    "default_recording": True,
                },
            )
        )
        session.commit()
        return camera.id


def patch_runtime_success(monkeypatch):
    calls: list[dict[str, object]] = []

    def ensure_streams(self, desired, *args, **kwargs):
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
                "max_second": (
                    desired.max_second
                    if desired is not None
                    else 0
                ),
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
        runtime = body["runtime"]
        assert runtime["desired_mode"] == "persistent"
        assert runtime["recording"] is True
        assert runtime["changed"] is True
        assert runtime["assumed_existing_mode"] is False
        assert runtime["observed_at"] is not None
        assert calls[0]["kind"] == "media"
        assert calls[1] == {
            "kind": "recorder",
            "mode": "persistent",
            "max_second": 300,
            "force": True,
        }

        fetched = client.get(
            f"/api/v1/cameras/{camera_id}/recording-policy"
        )
        assert fetched.status_code == 200
        # A bound RECORD camera always reports its observed runtime, even
        # when the media runtime cannot be reached.
        assert fetched.json()["runtime"]["recording"] is None
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

        tuning = client.patch(
            "/api/v1/system/settings",
            json={
                "runtime": {
                    "prebuffer_fragment_seconds": 7,
                }
            },
        )
        assert tuning.status_code == 200

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
        assert calls[-1]["max_second"] == 7

        updated_tuning = client.patch(
            "/api/v1/system/settings",
            json={
                "runtime": {
                    "prebuffer_fragment_seconds": 9,
                }
            },
        )
        assert updated_tuning.status_code == 200
        assert app.state.recording_tasks.runtime_calls == [
            (camera_id, False, True)
        ]


def test_policy_runtime_failure_does_not_roll_back_canonical_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    def ensure_streams(self, desired, *args, **kwargs):
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
        body = response.json()
        assert body["baseline_mode"] == "schedule"
        assert body["schedule_timezone"] == "UTC"
        assert body["schedule"] == payload["schedule"]

        fetched = client.get(
            f"/api/v1/cameras/{camera_id}/recording-policy"
        )
        assert fetched.status_code == 200
        fetched_body = fetched.json()
        assert fetched_body["schedule_timezone"] == "UTC"
        assert fetched_body["schedule"] == payload["schedule"]

    tasks = app.state.recording_tasks
    assert len(tasks.scheduled) == 1
    scheduled = tasks.scheduled[0]
    assert scheduled["policy_id"] == uuid.UUID(
        response.json()["id"]
    )
    assert scheduled["policy_version"]
    assert scheduled["eta"].tzinfo is not None


def test_policy_put_when_stream_is_offline_succeeds_with_offline_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    def offline_reconcile(self, desired, *, force_reconfigure=False):
        raise ApiError(
            status_code=503,
            code="recording_stream_offline",
            message="Camera recording stream is not available in ZLMediaKit.",
        )

    monkeypatch.setattr(
        recording_api.CameraMediaRuntimeService,
        "ensure_streams",
        lambda self, desired, *args, **kwargs: [],
    )
    monkeypatch.setattr(
        recording_api.RecordingRuntimeService,
        "reconcile",
        offline_reconcile,
    )

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)

        response = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["baseline_mode"] == "continuous"
        runtime = body["runtime"]
        assert runtime["desired_mode"] == "persistent"
        assert runtime["recording"] is False
        assert runtime["stream_online"] is False
        assert runtime["changed"] is False
        assert runtime["assumed_existing_mode"] is False
        # Verify background reconciliation task was enqueued
        assert len(app.state.recording_tasks.runtime_calls) == 1
        assert app.state.recording_tasks.runtime_calls[0] == (
            camera_id,
            False,
            True,
        )


def test_list_recording_policies(tmp_path: Path, monkeypatch):
    app = make_app(tmp_path)
    patch_runtime_success(monkeypatch)
    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)

        # Before putting policy, list is empty
        res = client.get("/api/v1/recording-policies")
        assert res.status_code == 200
        assert res.json() == []

        # Put a policy
        put_res = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert put_res.status_code == 200

        # Now list contains the policy
        res2 = client.get("/api/v1/recording-policies")
        assert res2.status_code == 200
        items = res2.json()
        assert len(items) == 1
        assert items[0]["camera_id"] == str(camera_id)
        assert items[0]["baseline_mode"] == "continuous"


def test_policy_runtime_resolution_when_active(tmp_path: Path, monkeypatch):
    app = make_app(tmp_path)
    patch_runtime_success(monkeypatch)
    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)

        put_res = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert put_res.status_code == 200

        # Simulate recorder actively running
        with app.state.database.session() as session:
            camera = CameraService.get_camera(session, camera_id)
            record_binding = next(
                b for b in camera.stream_bindings if b.purpose == "RECORD"
            )
            ref = recording_api.CameraMediaRuntimeService.reference_for(
                camera_id=camera_id,
                profile_id=record_binding.stream_profile_id,
            )
            app.state.recorder_modes.set(
                app=ref.app,
                stream=ref.stream,
                mode="persistent",
            )

        # GET single policy: the desired mode still comes from the tracker,
        # but recording state must come from the media runtime. Without a
        # reachable media runtime that is "unknown", never "recording".
        get_res = client.get(f"/api/v1/cameras/{camera_id}/recording-policy")
        assert get_res.status_code == 200
        runtime = get_res.json()["runtime"]
        assert runtime["desired_mode"] == "persistent"
        assert runtime["recording"] is None
        assert runtime["stream_online"] is None

        # GET list reports the same honest state
        list_res = client.get("/api/v1/recording-policies")
        assert list_res.status_code == 200
        assert list_res.json()[0]["runtime"]["recording"] is None


def test_auto_close_resolution_for_background_streams(tmp_path: Path):
    app = make_app(tmp_path)
    camera_id = seed_camera_and_storage(app)
    media_runtime = recording_api.CameraMediaRuntimeService(app.state.settings)

    with app.state.database.session() as session:
        camera = CameraService.get_camera(session, camera_id)
        record_binding = next(
            b for b in camera.stream_bindings if b.purpose == "RECORD"
        )
        record_profile = next(
            p for p in camera.stream_profiles if p.id == record_binding.stream_profile_id
        )
        # Background RECORD stream should have auto_close = False
        desired_record = media_runtime.desired_stream(
            session,
            camera=camera,
            profile=record_profile,
        )
        assert desired_record.auto_close is False

        # If we create a temporary profile not in bindings, it should default to True
        non_background_profile = camera.stream_profiles[0]
        # Temporarily mock camera with empty stream_bindings
        from unittest.mock import MagicMock
        mock_camera = MagicMock()
        mock_camera.enabled = True
        mock_camera.id = camera.id
        mock_camera.stream_bindings = []
        desired_live_only = media_runtime.desired_stream(
            session,
            camera=mock_camera,
            profile=non_background_profile,
        )
        assert desired_live_only.auto_close is True





class FakeZlmAdapter:
    """Minimal ZLM stand-in for recorder observation."""

    def __init__(self, settings, items) -> None:
        self.settings = settings
        self.items = items
        self.queries: list[tuple[str, str]] = []

    def __enter__(self) -> "FakeZlmAdapter":
        return self

    def __exit__(self, *args) -> None:
        return None

    def get_media_list(self, *, app, stream, schema="rtsp"):
        self.queries.append((app, stream))
        if isinstance(self.items, Exception):
            raise self.items
        return list(self.items)


def patch_zlm_observation(monkeypatch, items) -> list[FakeZlmAdapter]:
    created: list[FakeZlmAdapter] = []

    def factory(settings):
        adapter = FakeZlmAdapter(settings, items)
        created.append(adapter)
        return adapter

    monkeypatch.setattr(
        recording_api,
        "ZlmAdapter",
        factory,
    )
    return created


def test_continuous_policy_reports_not_recording_when_stream_is_offline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The 24x7 policy is on, but nothing is recorded: say so.

    This is the exact production symptom: a policy that says "全天录像"
    while the media runtime has no online stream. The API must report the
    observation instead of echoing the policy back as "recording".
    """

    app = make_app(tmp_path)
    patch_runtime_success(monkeypatch)
    patch_zlm_observation(monkeypatch, [])

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)

        put_res = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert put_res.status_code == 200

        list_res = client.get("/api/v1/recording-policies")
        assert list_res.status_code == 200
        runtime = list_res.json()[0]["runtime"]

        assert runtime["stream_online"] is False
        assert runtime["recording"] is False
        assert runtime["observed_at"] is not None


def test_continuous_policy_reports_recording_when_media_runtime_says_so(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    patch_runtime_success(monkeypatch)
    patch_zlm_observation(
        monkeypatch,
        [{"stream": "profile-1", "isRecordingMP4": True}],
    )

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)

        put_res = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert put_res.status_code == 200

        list_res = client.get("/api/v1/recording-policies")
        runtime = list_res.json()[0]["runtime"]

        assert runtime["stream_online"] is True
        assert runtime["recording"] is True


def test_runtime_is_unknown_when_media_runtime_is_unreachable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    patch_runtime_success(monkeypatch)
    patch_zlm_observation(
        monkeypatch,
        ZlmIntegrationError(
            code="zlm_unreachable",
            message="media runtime unavailable",
        ),
    )

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)

        put_res = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert put_res.status_code == 200

        list_res = client.get("/api/v1/recording-policies")
        runtime = list_res.json()[0]["runtime"]

        # Unreachable media runtime is not the same as "not recording".
        assert runtime["stream_online"] is None
        assert runtime["recording"] is None


def test_plan_saves_without_record_binding_and_reports_the_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A camera without a RECORD binding must still be configurable.

    Refusing the save leaves the operator unable to record *and* unable to
    turn recording off, while the only feedback is a raw backend message.
    The plan is persisted and the reason is reported as a runtime blocker.
    """

    app = make_app(tmp_path)
    patch_runtime_success(monkeypatch)
    patch_zlm_observation(monkeypatch, [])

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)

        with app.state.database.session() as session:
            camera = CameraService.get_camera(session, camera_id)
            for binding in list(camera.stream_bindings):
                if binding.purpose == "RECORD":
                    session.delete(binding)
            session.commit()

        response = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["baseline_mode"] == "continuous"
        assert body["enabled"] is True
        assert body["runtime"]["blockers"] == [
            "recording_stream_binding_missing"
        ]
        assert body["runtime"]["recording"] is False

        # The plan really is persisted, not just echoed back.
        fetched = client.get(
            f"/api/v1/cameras/{camera_id}/recording-policy"
        )
        assert fetched.json()["baseline_mode"] == "continuous"


def test_plan_saves_without_storage_target_and_reports_the_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    patch_runtime_success(monkeypatch)
    patch_zlm_observation(monkeypatch, [])

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera_and_storage(app)

        with app.state.database.session() as session:
            for target in session.scalars(
                select(StorageTarget)
            ).all():
                session.delete(target)
            session.commit()

        response = client.put(
            f"/api/v1/cameras/{camera_id}/recording-policy",
            json=continuous_payload(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert (
            "recording_storage_target_unconfigured"
            in body["runtime"]["blockers"]
        )
