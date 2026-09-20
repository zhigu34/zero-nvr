from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base, Database
from app.core.errors import ApiError
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.recordings.catalog import (
    FinalizedRecordingEvidence,
    RecordingCatalogService,
)
from app.modules.recordings.models import (
    RecordingLocation,
    RecordingPolicy,
    RecordingSegment,
    RecordingTrigger,
)
from app.modules.storage.models import StorageTarget


def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key="recording-catalog-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'catalog.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed(
    settings: Settings,
    database: Database,
    *,
    mode: str = "CONTINUOUS",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
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
            kind="LOCAL_RECORDING",
            enabled=True,
            config_json={
                "path": "/recordings",
                "default_recording": True,
            },
            health_state="OK",
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

        session.add(
            RecordingPolicy(
                camera_id=camera.id,
                mode=mode,
                enabled=True,
                storage_target_id=target.id,
                segment_target_seconds=300,
            )
        )
        session.commit()
        return camera.id, profile_id, target.id


def evidence(
    *,
    profile_id: uuid.UUID,
    start: float,
    duration: float,
    file_name: str,
    size: int = 1_000_000,
    root: str = "/recordings",
) -> FinalizedRecordingEvidence:
    return FinalizedRecordingEvidence(
        vhost="__defaultVhost__",
        app="zero-nvr",
        stream=f"profile-{profile_id.hex}",
        start_time_epoch=start,
        duration_seconds=duration,
        file_size=size,
        file_path=f"{root}/front-door/{file_name}",
    )


def test_same_continuity_next_boundary_finalizes_previous_and_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        _camera_id, profile_id, _target_id = seed(settings, database)
        continuity = uuid.uuid4()

        with database.session() as session:
            first = RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=1_000,
                    duration=8.0,
                    file_name="001.mp4",
                ),
                continuity_id=continuity,
            )
            assert first.created is True
            assert first.segment is not None
            first_id = first.segment.id
            session.commit()

        with database.session() as session:
            second = RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=1_009,
                    duration=8.0,
                    file_name="002.mp4",
                ),
                continuity_id=continuity,
            )
            assert second.created is True
            assert second.segment is not None
            second_id = second.segment.id
            session.commit()

        with database.session() as session:
            first_row = session.get(RecordingSegment, first_id)
            second_row = session.get(RecordingSegment, second_id)
            assert first_row is not None
            assert second_row is not None

            # Raw first hook said 1000..1008. The proven next same-session
            # boundary at 1009 normalizes it to 1001..1009.
            assert first_row.started_at == datetime.fromtimestamp(1001, UTC)
            assert first_row.ended_at == datetime.fromtimestamp(1009, UTC)
            assert first_row.timing_status == "FINAL"
            assert first_row.timing_source == "NEXT_SEGMENT_BOUNDARY"

            assert second_row.started_at == datetime.fromtimestamp(1009, UTC)
            assert second_row.ended_at == datetime.fromtimestamp(1017, UTC)
            assert second_row.timing_status == "PROVISIONAL"
            assert second_row.timing_source == "HOOK_RAW"

        with database.session() as session:
            retry = RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=1_009,
                    duration=8.0,
                    file_name="002.mp4",
                ),
                continuity_id=continuity,
            )
            assert retry.created is False
            assert retry.segment is not None
            assert retry.segment.id == second_id
            session.commit()

            assert session.scalar(
                select(func.count()).select_from(RecordingSegment)
            ) == 2
            assert session.scalar(
                select(func.count()).select_from(RecordingLocation)
            ) == 2
    finally:
        database.close()


def test_new_continuity_never_normalizes_previous_session(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        _camera_id, profile_id, _target_id = seed(settings, database)
        old_continuity = uuid.uuid4()
        new_continuity = uuid.uuid4()

        with database.session() as session:
            first = RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=2_000,
                    duration=8,
                    file_name="old.mp4",
                ),
                continuity_id=old_continuity,
            )
            assert first.segment is not None
            first_id = first.segment.id
            session.commit()

        with database.session() as session:
            RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=2_030,
                    duration=8,
                    file_name="new.mp4",
                ),
                continuity_id=new_continuity,
            )
            session.commit()

        with database.session() as session:
            first_row = session.get(RecordingSegment, first_id)
            assert first_row is not None
            assert first_row.timing_status == "PROVISIONAL"
            assert first_row.started_at == datetime.fromtimestamp(2000, UTC)
            assert first_row.ended_at == datetime.fromtimestamp(2008, UTC)
    finally:
        database.close()


def test_source_unregister_finalizes_only_that_continuity_tail(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        _camera_id, profile_id, _target_id = seed(settings, database)
        continuity = uuid.uuid4()

        with database.session() as session:
            result = RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=3_000,
                    duration=10,
                    file_name="tail.mp4",
                ),
                continuity_id=continuity,
            )
            assert result.segment is not None
            segment_id = result.segment.id
            session.commit()

        with database.session() as session:
            finalized = RecordingCatalogService.finalize_continuity_tail(
                session,
                continuity_id=continuity,
                boundary_at=datetime.fromtimestamp(3012, UTC),
            )
            assert finalized is not None
            session.commit()

        with database.session() as session:
            row = session.get(RecordingSegment, segment_id)
            assert row is not None
            assert row.started_at == datetime.fromtimestamp(3002, UTC)
            assert row.ended_at == datetime.fromtimestamp(3012, UTC)
            assert row.timing_status == "FINAL"
            assert row.timing_source == "SOURCE_UNREGISTER"
    finally:
        database.close()


def test_event_only_tmpfs_fragment_is_not_canonical_until_promoted(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        _camera_id, profile_id, _target_id = seed(
            settings,
            database,
            mode="EVENT_ONLY",
        )

        with database.session() as session:
            result = RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=4_000,
                    duration=5,
                    file_name="fragment.mp4",
                    root="/dev/shm/zero-nvr-prebuffer",
                ),
                continuity_id=uuid.uuid4(),
            )
            assert result.ignored is True
            assert result.ignore_reason == "event_only_ephemeral"
            session.commit()

            assert session.scalar(
                select(func.count()).select_from(RecordingSegment)
            ) == 0

        # The same finalized fragment copied/promoted under the persistent
        # recording target becomes a normal canonical segment.
        with database.session() as session:
            promoted = RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=4_000,
                    duration=5,
                    file_name="promoted.mp4",
                ),
                continuity_id=uuid.uuid4(),
            )
            assert promoted.created is True
            session.commit()
    finally:
        database.close()


def test_continuous_recording_rejects_path_outside_configured_target(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        _camera_id, profile_id, _target_id = seed(settings, database)

        with database.session() as session:
            with pytest.raises(ApiError) as captured:
                RecordingCatalogService.ingest_finalized(
                    session,
                    evidence=evidence(
                        profile_id=profile_id,
                        start=5_000,
                        duration=10,
                        file_name="escape.mp4",
                        root="/tmp/not-recordings",
                    ),
                    continuity_id=uuid.uuid4(),
                )
            assert captured.value.code == "recording_file_outside_target"
    finally:
        database.close()


def test_overlapping_trigger_annotates_event_reason(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, _target_id = seed(settings, database)
        start = datetime.fromtimestamp(6000, UTC)

        with database.session() as session:
            session.add(
                RecordingTrigger(
                    camera_id=camera_id,
                    type="AI_OBJECT",
                    source="frigate",
                    source_event_id="person-1",
                    planned_start_at=start - timedelta(seconds=2),
                    planned_end_at=start + timedelta(seconds=20),
                    state="ACTIVE",
                )
            )
            session.commit()

        with database.session() as session:
            result = RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=6000,
                    duration=10,
                    file_name="event.mp4",
                ),
                continuity_id=uuid.uuid4(),
            )
            assert result.segment is not None
            assert result.segment.recording_reasons == [
                "continuous",
                "event",
            ]
    finally:
        database.close()


def test_same_path_with_changed_size_is_conflict(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        _camera_id, profile_id, _target_id = seed(settings, database)
        continuity = uuid.uuid4()

        with database.session() as session:
            RecordingCatalogService.ingest_finalized(
                session,
                evidence=evidence(
                    profile_id=profile_id,
                    start=7000,
                    duration=10,
                    file_name="same.mp4",
                    size=100,
                ),
                continuity_id=continuity,
            )
            session.commit()

        with database.session() as session:
            with pytest.raises(ApiError) as captured:
                RecordingCatalogService.ingest_finalized(
                    session,
                    evidence=evidence(
                        profile_id=profile_id,
                        start=7000,
                        duration=10,
                        file_name="same.mp4",
                        size=101,
                    ),
                    continuity_id=continuity,
                )
            assert captured.value.code == "recording_location_conflict"
    finally:
        database.close()
