from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
    RecordingTrigger,
)
from app.modules.storage.models import RecordingLocation, StorageTarget


def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key="recording-model-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'recording-models.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed_camera_and_target(
    settings: Settings,
    database: Database,
):
    with database.session() as session:
        camera = CameraService(settings).create_manual_rtsp_camera(
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
            config_json={"path": "/recordings"},
        )
        session.add(target)
        session.flush()
        profile_id = session.scalar(
            select(CameraStreamProfile.id).where(
                CameraStreamProfile.camera_id == camera.id,
                CameraStreamProfile.adapter_profile_key == "manual-primary",
            )
        )
        assert profile_id is not None
        session.commit()
        return camera.id, profile_id, target.id


def test_one_recording_policy_per_camera(tmp_path: Path) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, _profile_id, target_id = seed_camera_and_target(
            settings,
            database,
        )

        with database.session() as session:
            session.add(
                RecordingPolicy(
                    camera_id=camera_id,
                    baseline_mode="continuous",
                    event_recording_enabled=False,
                    storage_target_id=target_id,
                )
            )
            session.commit()

        with database.session() as session:
            session.add(
                RecordingPolicy(
                    camera_id=camera_id,
                    baseline_mode="disabled",
                    event_recording_enabled=True,
                    storage_target_id=target_id,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        database.close()


def test_trigger_source_event_identity_is_unique_when_present(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, _profile_id, _target_id = seed_camera_and_target(
            settings,
            database,
        )
        start = datetime.now(UTC)

        with database.session() as session:
            session.add(
                RecordingTrigger(
                    camera_id=camera_id,
                    type="AI_OBJECT",
                    source="frigate",
                    source_event_id="event-123",
                    pre_roll_seconds=10,
                    post_roll_seconds=10,
                    planned_start_at=start,
                    planned_end_at=start + timedelta(seconds=20),
                    state="ACTIVE",
                    correlation_id="event-123",
                )
            )
            session.commit()

        with database.session() as session:
            session.add(
                RecordingTrigger(
                    camera_id=camera_id,
                    type="AI_OBJECT",
                    source="frigate",
                    source_event_id="event-123",
                    pre_roll_seconds=10,
                    post_roll_seconds=10,
                    planned_start_at=start + timedelta(seconds=1),
                    planned_end_at=start + timedelta(seconds=30),
                    state="ACTIVE",
                    correlation_id="event-123-retry",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

        # Triggers without source_event_id remain independent rows.
        with database.session() as session:
            session.add_all(
                [
                    RecordingTrigger(
                        camera_id=camera_id,
                        type="API",
                        source="api",
                        source_event_id=None,
                        pre_roll_seconds=0,
                        post_roll_seconds=5,
                        planned_start_at=start,
                        planned_end_at=start + timedelta(seconds=5),
                        state="COMPLETED",
                        correlation_id="manual-1",
                    ),
                    RecordingTrigger(
                        camera_id=camera_id,
                        type="API",
                        source="api",
                        source_event_id=None,
                        pre_roll_seconds=0,
                        post_roll_seconds=5,
                        planned_start_at=start,
                        planned_end_at=start + timedelta(seconds=5),
                        state="COMPLETED",
                        correlation_id="manual-2",
                    ),
                ]
            )
            session.commit()
    finally:
        database.close()


def test_physical_location_identity_is_target_plus_object_path(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, target_id = seed_camera_and_target(
            settings,
            database,
        )
        start = datetime.now(UTC)

        with database.session() as session:
            segment = RecordingSegment(
                camera_id=camera_id,
                stream_profile_id=profile_id,
                started_at=start,
                ended_at=start + timedelta(seconds=10),
                duration_ms=10_000,
                recording_reasons_json=["continuous"],
                size_bytes=1_000_000,
                codec="h264",
                container="fmp4",
                source_media_server_id="default",
                source_app="zero-nvr",
                source_stream=f"profile-{profile_id.hex}",
                integrity_status="OK",
                completion_reason="NORMAL",
                timing_status="PROVISIONAL",
                timing_source="HOOK_RAW",
            )
            session.add(segment)
            session.flush()
            session.add(
                RecordingLocation(
                    recording_segment_id=segment.id,
                    storage_target_id=target_id,
                    object_path="front-door/2026-09-20/segment-001.mp4",
                    state="AVAILABLE",
                    size_bytes=1_000_000,
                )
            )
            session.commit()
            segment_id = segment.id

        with database.session() as session:
            session.add(
                RecordingLocation(
                    recording_segment_id=segment_id,
                    storage_target_id=target_id,
                    object_path="front-door/2026-09-20/segment-001.mp4",
                    state="AVAILABLE",
                    size_bytes=1_000_000,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        database.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"ended_at_delta": 0},
        {"duration_ms": -1},
        {"timing_status": "BROKEN"},
        {"timing_source": "MADE_UP"},
    ],
)
def test_recording_segment_constraints_are_database_enforced(
    tmp_path: Path,
    changes: dict[str, object],
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, _target_id = seed_camera_and_target(
            settings,
            database,
        )
        start = datetime.now(UTC)

        values = {
            "ended_at_delta": 10,
            "duration_ms": 10_000,
            "timing_status": "PROVISIONAL",
            "timing_source": "HOOK_RAW",
        }
        values.update(changes)

        with database.session() as session:
            session.add(
                RecordingSegment(
                    camera_id=camera_id,
                    stream_profile_id=profile_id,
                    started_at=start,
                    ended_at=start
                    + timedelta(seconds=int(values["ended_at_delta"])),
                    duration_ms=int(values["duration_ms"]),
                    recording_reasons_json=["continuous"],
                    size_bytes=1_000,
                    codec="h264",
                    container="fmp4",
                    source_media_server_id="default",
                    source_app="zero-nvr",
                    source_stream=f"profile-{profile_id.hex}",
                    integrity_status="UNKNOWN",
                    completion_reason=None,
                    timing_status=str(values["timing_status"]),
                    timing_source=str(values["timing_source"]),
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        database.close()
