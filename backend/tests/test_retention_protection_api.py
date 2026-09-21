from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import Role
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
)
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)


ADMIN_PASSWORD = "correct-horse-battery-staple"
OPERATOR_PASSWORD = "operator-correct-horse-battery"
VIEWER_PASSWORD = "viewer-correct-horse-battery"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="retention-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'retention-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=tmp_path / "recordings",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
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
            "password": ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": ADMIN_PASSWORD,
        },
    )
    assert login.status_code == 200


def seed_camera(app, name: str) -> uuid.UUID:
    with app.state.database.session() as session:
        camera = CameraService(
            app.state.settings
        ).create_manual_rtsp_camera(
            session,
            name=name,
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url=f"rtsp://{name.lower().replace(' ', '-')}.local/main",
            secondary_name=None,
            secondary_url=None,
        )
        session.commit()
        return camera.id


def test_retention_policy_crud_scope_uniqueness_and_in_use_delete(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera(app, "Front Door")

        global_policy = client.post(
            "/api/v1/storage/retention-policies",
            json={
                "name": "Global",
                "scope_type": "GLOBAL",
                "scope_id": None,
                "ordinary_keep_days": 7,
                "event_keep_days": 30,
                "manual_keep_days": 90,
                "mode": "HARD",
                "require_archive_before_delete": True,
                "enabled": True,
            },
        )
        assert global_policy.status_code == 201
        global_id = global_policy.json()["id"]

        duplicate_global = client.post(
            "/api/v1/storage/retention-policies",
            json={
                "name": "Another Global",
                "scope_type": "GLOBAL",
                "ordinary_keep_days": 1,
                "event_keep_days": 1,
                "manual_keep_days": 1,
                "mode": "BEST_EFFORT",
            },
        )
        assert duplicate_global.status_code == 409
        assert (
            duplicate_global.json()["error"]["code"]
            == "retention_scope_conflict"
        )

        camera_policy = client.post(
            "/api/v1/storage/retention-policies",
            json={
                "name": "Front Door",
                "scope_type": "CAMERA",
                "scope_id": str(camera_id),
                "ordinary_keep_days": 14,
                "event_keep_days": 45,
                "manual_keep_days": 120,
                "mode": "HARD",
                "require_archive_before_delete": False,
                "enabled": True,
            },
        )
        assert camera_policy.status_code == 201
        camera_policy_id = camera_policy.json()["id"]

        invalid_scope = client.post(
            "/api/v1/storage/retention-policies",
            json={
                "name": "Broken",
                "scope_type": "CAMERA",
                "scope_id": None,
                "ordinary_keep_days": 1,
                "event_keep_days": 1,
                "manual_keep_days": 1,
                "mode": "HARD",
            },
        )
        assert invalid_scope.status_code == 400
        assert (
            invalid_scope.json()["error"]["code"]
            == "retention_scope_invalid"
        )

        patched = client.patch(
            f"/api/v1/storage/retention-policies/{camera_policy_id}",
            json={
                "event_keep_days": 60,
                "name": "Front Door Long Events",
            },
        )
        assert patched.status_code == 200
        assert patched.json()["event_keep_days"] == 60
        assert patched.json()["name"] == "Front Door Long Events"

        null_patch = client.patch(
            f"/api/v1/storage/retention-policies/{camera_policy_id}",
            json={"mode": None},
        )
        assert null_patch.status_code == 400
        assert (
            null_patch.json()["error"]["code"]
            == "retention_patch_null_invalid"
        )

        listed = client.get(
            "/api/v1/storage/retention-policies"
        )
        assert listed.status_code == 200
        assert {
            item["id"] for item in listed.json()
        } == {global_id, camera_policy_id}

        with app.state.database.session() as session:
            session.add(
                RecordingPolicy(
                    camera_id=camera_id,
                    baseline_mode="continuous",
                    retention_policy_id=uuid.UUID(
                        camera_policy_id
                    ),
                    enabled=True,
                )
            )
            session.commit()

        blocked = client.delete(
            f"/api/v1/storage/retention-policies/{camera_policy_id}"
        )
        assert blocked.status_code == 409
        assert (
            blocked.json()["error"]["code"]
            == "retention_policy_in_use"
        )

        deleted = client.delete(
            f"/api/v1/storage/retention-policies/{global_id}"
        )
        assert deleted.status_code == 204

    with app.state.database.session() as session:
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.resource_type
                    == "retention_policy"
                )
            ).all()
        )
    assert {
        "retention_policy.create",
        "retention_policy.update",
        "retention_policy.delete",
    } <= actions


def test_recording_protection_permissions_scope_and_delete_race(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        front_id = seed_camera(app, "Front Door")
        back_id = seed_camera(app, "Back Door")

        start = datetime(
            2026,
            9,
            20,
            12,
            0,
            tzinfo=UTC,
        )
        end = start + timedelta(minutes=10)

        created = client.post(
            f"/api/v1/cameras/{front_id}/recording-protections",
            json={
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
                "reason": "incident review",
            },
        )
        assert created.status_code == 201
        protection_id = created.json()["id"]

        updated_start = start + timedelta(minutes=1)
        updated_end = end + timedelta(minutes=5)
        updated_expiry = datetime.now(UTC) + timedelta(days=30)
        updated = client.put(
            f"/api/v1/recording-protections/{protection_id}",
            json={
                "started_at": updated_start.isoformat(),
                "ended_at": updated_end.isoformat(),
                "reason": "incident review updated",
                "expires_at": updated_expiry.isoformat(),
            },
        )
        assert updated.status_code == 200
        assert updated.json()["reason"] == "incident review updated"
        returned_start = datetime.fromisoformat(
            updated.json()["started_at"].replace("Z", "+00:00")
        )
        assert returned_start == updated_start
        assert updated.json()["expires_at"] is not None

        listed = client.get(
            f"/api/v1/cameras/{front_id}/recording-protections"
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [
            protection_id
        ]
        assert listed.json()[0]["reason"] == "incident review updated"

        with app.state.database.session() as session:
            operator_role = session.scalar(
                select(Role).where(Role.name == "Operator")
            )
            viewer_role = session.scalar(
                select(Role).where(Role.name == "Viewer")
            )
            assert operator_role is not None
            assert viewer_role is not None
            operator_role_id = operator_role.id
            viewer_role_id = viewer_role.id

        operator = client.post(
            "/api/v1/users",
            json={
                "username": "operator",
                "display_name": "Operator",
                "password": OPERATOR_PASSWORD,
                "role_ids": [str(operator_role_id)],
            },
        )
        assert operator.status_code == 201
        operator_id = operator.json()["id"]

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
        viewer_id = viewer.json()["id"]

        for user_id in (operator_id, viewer_id):
            scope = client.put(
                f"/api/v1/users/{user_id}/camera-scope",
                json={
                    "mode": "selected",
                    "camera_ids": [str(front_id)],
                },
            )
            assert scope.status_code == 200

        client.post("/api/v1/auth/logout")
        viewer_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "viewer",
                "password": VIEWER_PASSWORD,
            },
        )
        assert viewer_login.status_code == 200

        viewer_can_read = client.get(
            f"/api/v1/cameras/{front_id}/recording-protections"
        )
        assert viewer_can_read.status_code == 200

        viewer_denied = client.post(
            f"/api/v1/cameras/{front_id}/recording-protections",
            json={
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
                "reason": "viewer cannot protect",
            },
        )
        assert viewer_denied.status_code == 403

        viewer_update_denied = client.put(
            f"/api/v1/recording-protections/{protection_id}",
            json={
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
                "reason": "viewer cannot edit protection",
                "expires_at": None,
            },
        )
        assert viewer_update_denied.status_code == 403

        hidden = client.get(
            f"/api/v1/cameras/{back_id}/recording-protections"
        )
        assert hidden.status_code == 404

        client.post("/api/v1/auth/logout")
        operator_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "operator",
                "password": OPERATOR_PASSWORD,
            },
        )
        assert operator_login.status_code == 200

        operator_created = client.post(
            f"/api/v1/cameras/{front_id}/recording-protections",
            json={
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
                "reason": "operator hold",
            },
        )
        assert operator_created.status_code == 201

        removed = client.delete(
            f"/api/v1/recording-protections/{protection_id}"
        )
        assert removed.status_code == 204

        client.post("/api/v1/auth/logout")
        admin_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": ADMIN_PASSWORD,
            },
        )
        assert admin_login.status_code == 200

        with app.state.database.session() as session:
            target = StorageTarget(
                name="Local Recording",
                type="local",
                role="recording",
                enabled=True,
                config_json={
                    "path": str(app.state.settings.recordings_dir),
                    "default_recording": True,
                },
            )
            session.add(target)
            session.flush()

            profile_id = session.scalar(
                select(CameraStreamProfile.id).where(
                    CameraStreamProfile.camera_id == front_id,
                    CameraStreamProfile.adapter_profile_key
                    == "manual-primary",
                )
            )
            assert profile_id is not None

            segment = RecordingSegment(
                camera_id=front_id,
                stream_profile_id=profile_id,
                started_at=start,
                ended_at=end,
                duration_ms=600_000,
                timing_status="FINAL",
                timing_source="RECOVERY",
                recording_reasons_json=["continuous"],
                size_bytes=1000,
                codec="h264",
                container="fmp4",
                source_media_server_id="default",
                source_app="zero-nvr",
                source_stream=f"profile-{profile_id.hex}",
                integrity_status="OK",
                completion_reason="NORMAL",
            )
            session.add(segment)
            session.flush()
            session.add(
                RecordingLocation(
                    recording_segment_id=segment.id,
                    storage_target_id=target.id,
                    object_path="deleting.mp4",
                    state="DELETING",
                    size_bytes=1000,
                )
            )
            session.commit()

        race = client.post(
            f"/api/v1/cameras/{front_id}/recording-protections",
            json={
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
                "reason": "too late",
            },
        )
        assert race.status_code == 409
        assert (
            race.json()["error"]["code"]
            == "recording_deletion_in_progress"
        )

    with app.state.database.session() as session:
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.resource_type
                    == "recording_protection"
                )
            ).all()
        )
    assert {
        "recording_protection.create",
        "recording_protection.update",
        "recording_protection.delete",
    } <= actions
