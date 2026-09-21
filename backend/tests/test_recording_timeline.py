from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingPolicy, RecordingSegment
from app.modules.recordings.timeline import PlaybackTimelineService
from app.modules.storage.models import RecordingLocation, StorageTarget


def make_database(tmp_path: Path):
    settings = Settings(
        secret_key="timeline-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'timeline.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def test_timeline_merges_physical_segments_into_wall_clock_ranges(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
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
            local = StorageTarget(
                name="Local",
                type="local",
                role="recording",
                enabled=True,
                config_json={"path": "/recordings"},
            )
            remote = StorageTarget(
                name="Archive",
                type="rclone",
                role="archive",
                enabled=True,
                config_json={"remote": "archive:"},
            )
            session.add_all([local, remote])
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
                    baseline_mode="continuous",
                    event_recording_enabled=False,
                    storage_target_id=local.id,
                    enabled=True,
                )
            )

            base = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)

            def add_segment(
                start_minute: int,
                end_minute: int,
                target: StorageTarget,
                name: str,
            ) -> None:
                start = base + timedelta(minutes=start_minute)
                end = base + timedelta(minutes=end_minute)
                segment = RecordingSegment(
                    camera_id=camera.id,
                    stream_profile_id=profile_id,
                    started_at=start,
                    ended_at=end,
                    duration_ms=int((end - start).total_seconds() * 1000),
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
                        object_path=name,
                        state="AVAILABLE",
                        size_bytes=1000,
                    )
                )

            add_segment(0, 5, local, "local-1.mp4")
            add_segment(5, 10, local, "local-2.mp4")
            add_segment(8, 12, remote, "remote-1.mp4")
            session.commit()
            camera_id = camera.id

        with database.session() as session:
            timeline = PlaybackTimelineService.build(
                session,
                camera_id=camera_id,
                start_at=base,
                end_at=base + timedelta(minutes=15),
            )

        assert [
            (
                item.start_at,
                item.end_at,
                item.availability,
            )
            for item in timeline.recording_ranges
        ] == [
            (
                base,
                base + timedelta(minutes=10),
                "local",
            ),
            (
                base + timedelta(minutes=10),
                base + timedelta(minutes=12),
                "remote",
            ),
        ]
        assert len(timeline.gaps) == 1
        assert timeline.gaps[0].start_at == base + timedelta(minutes=12)
        assert timeline.gaps[0].end_at == base + timedelta(minutes=15)
        assert timeline.gaps[0].reason == "unknown"

        with database.session() as session:
            last_segment = session.scalar(
                select(RecordingSegment)
                .where(
                    RecordingSegment.camera_id
                    == camera_id
                )
                .order_by(
                    RecordingSegment.ended_at.desc()
                )
                .limit(1)
            )
            assert last_segment is not None
            last_segment.completion_reason = (
                "source_lost"
            )
            session.commit()

        with database.session() as session:
            source_loss_timeline = (
                PlaybackTimelineService.build(
                    session,
                    camera_id=camera_id,
                    start_at=base,
                    end_at=(
                        base
                        + timedelta(minutes=15)
                    ),
                )
            )

        assert len(
            source_loss_timeline.gaps
        ) == 1
        assert (
            source_loss_timeline.gaps[0].reason
            == "source_lost"
        )
    finally:
        database.close()
