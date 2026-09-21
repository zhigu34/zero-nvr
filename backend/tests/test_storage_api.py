from __future__ import annotations

import uuid
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.cameras.service import CameraService
from app.modules.auth.models import SecretRecord
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
)
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)
from app.modules.storage.recording_resolver import (
    RecordingStorageResolver,
)


ADMIN_PASSWORD = "correct-horse-battery-staple"
VIEWER_PASSWORD = "viewer-correct-horse-battery"
RCLONE_SECRET = """[archive]
type = webdav
url = https://example.invalid/dav
user = archive
pass = super-secret-rclone-password
"""


class FakeRecordingTasks:
    def __init__(self) -> None:
        self.reconciled: list[
            dict[str, object]
        ] = []

    def reconcile_runtime(
        self,
        camera_id: uuid.UUID,
        *,
        restart_streams: bool = False,
        force_reconfigure: bool = False,
    ) -> None:
        self.reconciled.append(
            {
                "camera_id": camera_id,
                "restart_streams": (
                    restart_streams
                ),
                "force_reconfigure": (
                    force_reconfigure
                ),
            }
        )



def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="storage-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'storage.db'}",
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


def test_storage_target_secret_is_encrypted_and_never_returned(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        local_root = tmp_path / "recordings"
        local_root.mkdir(parents=True, exist_ok=True)
        local = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Local Recording",
                "enabled": True,
                "config": {
                    "path": str(local_root),
                    "default_recording": True,
                },
            },
        )
        assert local.status_code == 201
        assert local.json()["credentials_configured"] is False
        assert local.json()["config"]["warning_used_percent"] == 80
        assert local.json()["config"]["high_used_percent"] == 85
        assert local.json()["config"]["critical_used_percent"] == 95

        remote = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "rclone",
                "role": "archive",
                "name": "Cloud Archive",
                "enabled": True,
                "config": {
                    "remote": "archive",
                    "base_path": "zero-nvr/archive",
                },
                "rclone_config": RCLONE_SECRET,
            },
        )
        assert remote.status_code == 201
        remote_body = remote.json()
        assert remote_body["credentials_configured"] is True
        assert remote_body["config"] == {
            "remote": "archive",
            "base_path": "zero-nvr/archive",
        }
        assert "super-secret-rclone-password" not in remote.text
        assert "example.invalid" not in json.dumps(
            remote_body["config"]
        )

        listed = client.get("/api/v1/storage/targets")
        assert listed.status_code == 200
        serialized = listed.text
        assert "super-secret-rclone-password" not in serialized
        assert "pass =" not in serialized

        local_test = client.post(
            f"/api/v1/storage/targets/{local.json()['id']}/test"
        )
        assert local_test.status_code == 200
        assert local_test.json()["detail"] == "read_write_ok"
        assert local_test.json()["free_bytes"] > 0
        assert local_test.json()["total_bytes"] > 0
        assert 0 <= local_test.json()["used_percent"] <= 100
        assert local_test.json()["capacity_level"] in {
            "normal",
            "warning",
            "high",
            "critical",
        }
        assert local_test.json()["warning_percent"] == 80
        assert local_test.json()["high_percent"] == 85
        assert local_test.json()["critical_percent"] == 95

        invalid_watermarks = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Bad Watermarks",
                "enabled": True,
                "config": {
                    "path": str(tmp_path / "bad-watermarks"),
                    "warning_used_percent": 90,
                    "high_used_percent": 85,
                    "critical_used_percent": 95,
                },
            },
        )
        assert invalid_watermarks.status_code == 400
        assert (
            invalid_watermarks.json()["error"]["code"]
            == "storage_watermark_invalid"
        )

        conflict = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Another Default",
                "enabled": True,
                "config": {
                    "path": str(tmp_path / "other"),
                    "default_recording": True,
                },
            },
        )
        assert conflict.status_code == 409
        assert (
            conflict.json()["error"]["code"]
            == "default_recording_target_conflict"
        )

        with app.state.database.session() as session:
            target = session.get(
                StorageTarget,
                uuid.UUID(remote_body["id"]),
            )
            assert target is not None
            assert target.credential_secret_ref is not None
            secret = session.get(
                SecretRecord,
                target.credential_secret_ref,
            )
            assert secret is not None
            assert b"super-secret-rclone-password" not in (
                secret.encrypted_payload
            )
            assert b"example.invalid" not in secret.encrypted_payload

            audit_json = json.dumps(
                [
                    {
                        "before": row.before_json,
                        "after": row.after_json,
                    }
                    for row in session.scalars(
                        select(AuditEvent).where(
                            AuditEvent.resource_type
                            == "storage_target"
                        )
                    )
                ]
            )
            assert "super-secret-rclone-password" not in audit_json
            assert "pass =" not in audit_json


def test_persisted_default_local_recording_target_is_resolved(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    primary_root = tmp_path / "recordings-primary"
    secondary_root = tmp_path / "recordings-secondary"
    primary_root.mkdir(parents=True)
    secondary_root.mkdir(parents=True)

    with TestClient(app) as client:
        setup_admin(client)

        primary = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Primary Recording",
                "enabled": True,
                "config": {
                    "path": str(primary_root),
                    "default_recording": True,
                },
            },
        )
        assert primary.status_code == 201
        primary_id = uuid.UUID(
            primary.json()["id"]
        )

        secondary = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Secondary Recording",
                "enabled": True,
                "config": {
                    "path": str(secondary_root),
                    "default_recording": False,
                },
            },
        )
        assert secondary.status_code == 201

        with app.state.database.session() as session:
            camera = CameraService(
                app.state.settings
            ).create_manual_rtsp_camera(
                session,
                name="Implicit Storage Camera",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url=(
                    "rtsp://camera.local/implicit"
                ),
                secondary_name=None,
                secondary_url=None,
            )
            session.add(
                RecordingPolicy(
                    camera_id=camera.id,
                    baseline_mode="continuous",
                    storage_target_id=None,
                    enabled=True,
                )
            )
            session.commit()
            camera_id = camera.id

    # Re-open a database session after the API/client scope to prove the
    # default lives in durable StorageTarget state rather than process memory.
    with app.state.database.session() as session:
        resolved = (
            RecordingStorageResolver
            .local_target_for_camera(
                session,
                camera_id=camera_id,
            )
        )
        assert resolved.target.id == primary_id
        assert resolved.root == primary_root.resolve()


def test_storage_target_delete_is_blocked_while_policy_references_it(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        root = tmp_path / "recordings"
        root.mkdir(parents=True, exist_ok=True)
        created = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Local Recording",
                "config": {
                    "path": str(root),
                    "default_recording": True,
                },
            },
        )
        assert created.status_code == 201

        # A direct policy reference is enough to protect target identity.
        with app.state.database.session() as session:
            from app.modules.cameras.service import CameraService

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
                RecordingPolicy(
                    camera_id=camera.id,
                    baseline_mode="continuous",
                    storage_target_id=uuid.UUID(created.json()["id"]),
                    enabled=True,
                )
            )
            session.commit()

        deleted = client.delete(
            f"/api/v1/storage/targets/{created.json()['id']}"
        )
        assert deleted.status_code == 409
        assert (
            deleted.json()["error"]["code"]
            == "storage_target_in_use"
        )



def test_storage_target_switch_preserves_historical_locations(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    tasks = FakeRecordingTasks()
    app.state.recording_tasks = tasks

    source_root = tmp_path / "recordings-a"
    destination_root = tmp_path / "recordings-b"
    source_root.mkdir(parents=True)
    destination_root.mkdir(parents=True)

    with TestClient(app) as client:
        setup_admin(client)

        source_response = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Primary A",
                "enabled": True,
                "config": {
                    "path": str(source_root),
                    "default_recording": True,
                },
            },
        )
        assert source_response.status_code == 201
        source_id = uuid.UUID(
            source_response.json()["id"]
        )

        destination_response = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Primary B",
                "enabled": True,
                "config": {
                    "path": str(destination_root),
                    "default_recording": False,
                },
            },
        )
        assert destination_response.status_code == 201
        destination_id = uuid.UUID(
            destination_response.json()["id"]
        )

        with app.state.database.session() as session:
            explicit_camera = (
                CameraService(
                    app.state.settings
                ).create_manual_rtsp_camera(
                    session,
                    name="Front Door",
                    location=None,
                    storage_label=None,
                    primary_name="Main",
                    primary_url=(
                        "rtsp://camera.local/front"
                    ),
                    secondary_name=None,
                    secondary_url=None,
                )
            )
            implicit_camera = (
                CameraService(
                    app.state.settings
                ).create_manual_rtsp_camera(
                    session,
                    name="Garage",
                    location=None,
                    storage_label=None,
                    primary_name="Main",
                    primary_url=(
                        "rtsp://camera.local/garage"
                    ),
                    secondary_name=None,
                    secondary_url=None,
                )
            )
            session.add_all(
                [
                    RecordingPolicy(
                        camera_id=(
                            explicit_camera.id
                        ),
                        baseline_mode="continuous",
                        storage_target_id=(
                            source_id
                        ),
                        enabled=True,
                    ),
                    RecordingPolicy(
                        camera_id=(
                            implicit_camera.id
                        ),
                        baseline_mode="continuous",
                        storage_target_id=None,
                        enabled=True,
                    ),
                ]
            )
            started_at = datetime(
                2026,
                9,
                21,
                12,
                0,
                tzinfo=UTC,
            )
            segment = RecordingSegment(
                camera_id=explicit_camera.id,
                stream_profile_id=None,
                started_at=started_at,
                ended_at=(
                    started_at
                    + timedelta(minutes=5)
                ),
                duration_ms=300_000,
                timing_status="FINAL",
                timing_source="HOOK_RAW",
                recording_reasons_json=[
                    "continuous"
                ],
                size_bytes=1024,
                codec="h264",
                container="mp4",
                source_media_server_id="zlm",
                source_app="live",
                source_stream="front-main",
                integrity_status="UNKNOWN",
                completion_reason="normal",
            )
            session.add(segment)
            session.flush()
            historical_location = (
                RecordingLocation(
                    recording_segment_id=(
                        segment.id
                    ),
                    storage_target_id=source_id,
                    object_path=(
                        "2026/09/21/front.mp4"
                    ),
                    state="AVAILABLE",
                    size_bytes=1024,
                )
            )
            session.add(historical_location)
            session.commit()
            explicit_camera_id = (
                explicit_camera.id
            )
            implicit_camera_id = (
                implicit_camera.id
            )
            historical_location_id = (
                historical_location.id
            )

        path_change = client.patch(
            (
                "/api/v1/storage/targets/"
                f"{source_id}"
            ),
            json={
                "config": {
                    "path": str(
                        tmp_path / "unsafe-new-root"
                    ),
                    "default_recording": True,
                }
            },
        )
        assert path_change.status_code == 409
        assert (
            path_change.json()["error"]["code"]
            == "storage_target_path_immutable"
        )

        switched = client.post(
            (
                "/api/v1/storage/targets/"
                f"{source_id}/switch-recording"
            ),
            json={
                "destination_target_id": (
                    str(destination_id)
                )
            },
        )
        assert switched.status_code == 200
        body = switched.json()
        assert (
            body["explicit_policies_updated"]
            == 1
        )
        assert (
            body["implicit_policies_rebound"]
            == 1
        )
        assert body["default_moved"] is True
        assert set(
            body["affected_camera_ids"]
        ) == {
            str(explicit_camera_id),
            str(implicit_camera_id),
        }

    with app.state.database.session() as session:
        explicit_policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id
                == explicit_camera_id
            )
        )
        implicit_policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id
                == implicit_camera_id
            )
        )
        assert explicit_policy is not None
        assert implicit_policy is not None
        assert (
            explicit_policy.storage_target_id
            == destination_id
        )
        assert (
            implicit_policy.storage_target_id
            is None
        )

        source = session.get(
            StorageTarget,
            source_id,
        )
        destination = session.get(
            StorageTarget,
            destination_id,
        )
        assert source is not None
        assert destination is not None
        assert (
            source.config_json[
                "default_recording"
            ]
            is False
        )
        assert (
            destination.config_json[
                "default_recording"
            ]
            is True
        )
        assert source.config_json["path"] == str(
            source_root.resolve()
        )
        assert (
            destination.config_json["path"]
            == str(destination_root.resolve())
        )

        location = session.get(
            RecordingLocation,
            historical_location_id,
        )
        assert location is not None
        assert (
            location.storage_target_id
            == source_id
        )
        assert (
            location.object_path
            == "2026/09/21/front.mp4"
        )

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action
                == (
                    "storage_target."
                    "recording_route_switch"
                )
            )
        )
        assert audit is not None

    assert {
        item["camera_id"]
        for item in tasks.reconciled
    } == {
        explicit_camera_id,
        implicit_camera_id,
    }
    assert all(
        item["force_reconfigure"]
        is True
        for item in tasks.reconciled
    )
    assert all(
        item["restart_streams"]
        is False
        for item in tasks.reconciled
    )
