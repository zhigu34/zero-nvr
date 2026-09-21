from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.cameras.models import (
    CameraStreamProfile,
)
from app.modules.cameras.service import (
    CameraService,
)
from app.modules.events.models import Event
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
)
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)


ADMIN_PASSWORD = (
    "correct-horse-battery-staple"
)


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key=(
            "timeline-api-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'timeline-api.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=(
            tmp_path / "recordings"
        ),
        prebuffer_dir=(
            tmp_path / "prebuffer"
        ),
        prebuffer_require_tmpfs=False,
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(
        app.state.database.engine
    )
    return app


def setup_admin(client: TestClient) -> None:
    created = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": (
                "Administrator"
            ),
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


def seed_timeline(app):
    base = datetime(
        2026,
        9,
        20,
        0,
        0,
        tzinfo=UTC,
    )
    app.state.settings.recordings_dir.mkdir(
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
            primary_url=(
                "rtsp://camera.local/main"
            ),
            secondary_name=None,
            secondary_url=None,
        )
        local = StorageTarget(
            name="Local Recording",
            type="local",
            role="recording",
            enabled=True,
            config_json={
                "path": str(
                    app.state.settings
                    .recordings_dir
                ),
                "default_recording": True,
            },
        )
        session.add(local)
        session.flush()

        profile_id = session.scalar(
            select(
                CameraStreamProfile.id
            ).where(
                CameraStreamProfile.camera_id
                == camera.id,
                CameraStreamProfile
                .adapter_profile_key
                == "manual-primary",
            )
        )
        assert profile_id is not None

        session.add(
            RecordingPolicy(
                camera_id=camera.id,
                baseline_mode="continuous",
                event_recording_enabled=False,
                storage_target_id=local.id,
                enabled=True,
            )
        )

        segment = RecordingSegment(
            camera_id=camera.id,
            stream_profile_id=profile_id,
            started_at=base,
            ended_at=(
                base
                + timedelta(minutes=5)
            ),
            duration_ms=300_000,
            timing_status="FINAL",
            timing_source="RECOVERY",
            recording_reasons_json=[
                "continuous"
            ],
            size_bytes=1000,
            codec="h264",
            container="fmp4",
            source_media_server_id=(
                "default"
            ),
            source_app="zero-nvr",
            source_stream=(
                f"profile-{profile_id.hex}"
            ),
            integrity_status="OK",
            completion_reason="NORMAL",
        )
        session.add(segment)
        session.flush()

        session.add(
            RecordingLocation(
                recording_segment_id=(
                    segment.id
                ),
                storage_target_id=local.id,
                object_path=(
                    "record/front-door/"
                    "segment-001.mp4"
                ),
                state="AVAILABLE",
                size_bytes=1000,
            )
        )
        event = Event(
            source="frigate",
            source_instance_id=(
                "timeline-api-test"
            ),
            source_event_id="event-1",
            camera_id=camera.id,
            category="object",
            label="person",
            started_at=(
                base
                + timedelta(minutes=2)
            ),
            ended_at=(
                base
                + timedelta(minutes=3)
            ),
            severity="info",
            metadata_json={},
        )
        session.add(event)
        session.commit()
        return camera.id, event.id, base


def test_timeline_api_normalizes_timezone_and_projects_ranges(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        (
            camera_id,
            event_id,
            base,
        ) = seed_timeline(app)

        response = client.get(
            (
                f"/api/v1/cameras/"
                f"{camera_id}/timeline"
            ),
            params={
                "from": (
                    "2026-09-20T08:00:00"
                    "+08:00"
                ),
                "to": (
                    "2026-09-20T08:10:00"
                    "+08:00"
                ),
            },
        )
        assert response.status_code == 200
        body = response.json()

        assert (
            body["camera_id"]
            == str(camera_id)
        )
        assert (
            datetime.fromisoformat(
                body["range"]["start_at"]
            )
            == base
        )
        assert (
            datetime.fromisoformat(
                body["range"]["end_at"]
            )
            == base
            + timedelta(minutes=10)
        )

        assert len(
            body["recording_ranges"]
        ) == 1
        recording = (
            body["recording_ranges"][0]
        )
        assert (
            recording["availability"]
            == "local"
        )
        assert (
            datetime.fromisoformat(
                recording["start_at"]
            )
            == base
        )
        assert (
            datetime.fromisoformat(
                recording["end_at"]
            )
            == base
            + timedelta(minutes=5)
        )

        assert body["gaps"] == [
            {
                "start_at": (
                    base
                    + timedelta(minutes=5)
                ).isoformat(),
                "end_at": (
                    base
                    + timedelta(minutes=10)
                ).isoformat(),
                "reason": "unknown",
            }
        ]

        assert len(body["events"]) == 1
        marker = body["events"][0]
        assert marker["id"] == str(
            event_id
        )
        assert marker["category"] == (
            "object"
        )
        assert marker["label"] == (
            "person"
        )


def test_timeline_api_rejects_naive_and_invalid_ranges(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id, _, _ = (
            seed_timeline(app)
        )
        path = (
            f"/api/v1/cameras/"
            f"{camera_id}/timeline"
        )

        naive = client.get(
            path,
            params={
                "from": (
                    "2026-09-20T00:00:00"
                ),
                "to": (
                    "2026-09-20T00:10:00Z"
                ),
            },
        )
        assert naive.status_code == 422
        assert (
            naive.json()["error"]["code"]
            == "timezone_required"
        )

        invalid = client.get(
            path,
            params={
                "from": (
                    "2026-09-20T00:10:00Z"
                ),
                "to": (
                    "2026-09-20T00:00:00Z"
                ),
            },
        )
        assert invalid.status_code == 422
        assert (
            invalid.json()["error"]["code"]
            == "invalid_time_range"
        )
