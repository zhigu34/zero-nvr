from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import Camera
from app.modules.recordings.models import RecordingSegment
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)
from app.modules.system.benchmark import (
    CameraBenchmarkStatus,
    ReleaseBenchmarkStatus,
)
from app.modules.system.camera_acceptance import (
    RealCameraAcceptanceService,
)


class FakeBenchmark:
    def __init__(
        self,
        camera_id: uuid.UUID,
    ) -> None:
        self.camera_id = camera_id

    def collect(
        self,
        *,
        expected_cameras: int,
    ) -> ReleaseBenchmarkStatus:
        assert expected_cameras == 1
        return ReleaseBenchmarkStatus(
            expected_cameras=1,
            enabled_cameras=1,
            recording_expected_cameras=1,
            record_streams_online=1,
            recorders_active=1,
            passed=True,
            failures=(),
            cameras=(
                CameraBenchmarkStatus(
                    camera_id=self.camera_id,
                    name="Front Door",
                    desired_mode="persistent",
                    stream_online=True,
                    recording_active=True,
                    error=None,
                ),
            ),
        )


def make_database(
    tmp_path: Path,
) -> tuple[
    Settings,
    Database,
    uuid.UUID,
    datetime,
]:
    settings = Settings(
        secret_key=(
            "real-camera-acceptance-test-secret-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'acceptance.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_require_tmpfs=False,
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(
        database.engine
    )
    started = datetime(
        2026,
        9,
        24,
        10,
        0,
        tzinfo=UTC,
    )
    with database.session() as session:
        camera = Camera(
            channel_key="front-door",
            name="Front Door",
            enabled=True,
        )
        target = StorageTarget(
            name="Local",
            type="local",
            role="recording",
            enabled=True,
            config_json={
                "path": str(
                    tmp_path
                    / "recordings"
                )
            },
        )
        session.add_all(
            [camera, target]
        )
        session.flush()
        segment = RecordingSegment(
            camera_id=camera.id,
            stream_profile_id=None,
            started_at=started,
            ended_at=(
                started
                + timedelta(minutes=5)
            ),
            duration_ms=300_000,
            timing_status="FINAL",
            timing_source=(
                "NEXT_SEGMENT_BOUNDARY"
            ),
            recording_reasons_json=[
                "continuous"
            ],
            size_bytes=1024,
            codec="h264",
            container="fmp4",
            source_media_server_id="default",
            source_app="zero-nvr",
            source_stream="profile-test",
            integrity_status="UNKNOWN",
            completion_reason="NORMAL",
            created_at=(
                started
                + timedelta(minutes=5)
            ),
        )
        session.add(segment)
        session.flush()
        session.add(
            RecordingLocation(
                recording_segment_id=(
                    segment.id
                ),
                storage_target_id=target.id,
                object_path=(
                    "front/segment-1.mp4"
                ),
                state="AVAILABLE",
                size_bytes=1024,
            )
        )
        session.commit()
        camera_id = camera.id
    return (
        settings,
        database,
        camera_id,
        started,
    )


def add_post_restart_segment(
    database: Database,
    camera_id: uuid.UUID,
    *,
    created_at: datetime,
) -> None:
    with database.session() as session:
        target = session.query(
            StorageTarget
        ).filter_by(
            name="Local"
        ).one()
        segment = RecordingSegment(
            camera_id=camera_id,
            stream_profile_id=None,
            started_at=(
                created_at
                - timedelta(minutes=5)
            ),
            ended_at=created_at,
            duration_ms=300_000,
            timing_status="FINAL",
            timing_source=(
                "NEXT_SEGMENT_BOUNDARY"
            ),
            recording_reasons_json=[
                "continuous"
            ],
            size_bytes=2048,
            codec="h264",
            container="fmp4",
            source_media_server_id="default",
            source_app="zero-nvr",
            source_stream="profile-test",
            integrity_status="UNKNOWN",
            completion_reason="NORMAL",
            created_at=created_at,
        )
        session.add(segment)
        session.flush()
        session.add(
            RecordingLocation(
                recording_segment_id=(
                    segment.id
                ),
                storage_target_id=target.id,
                object_path=(
                    "front/segment-2.mp4"
                ),
                state="AVAILABLE",
                size_bytes=2048,
            )
        )
        session.commit()


def test_real_camera_acceptance_two_phase_flow(
    tmp_path: Path,
) -> None:
    (
        settings,
        database,
        camera_id,
        started,
    ) = make_database(tmp_path)
    moments = iter(
        (
            started
            + timedelta(minutes=10),
            started
            + timedelta(minutes=11),
            started
            + timedelta(minutes=17),
            started
            + timedelta(minutes=18),
        )
    )
    service = RealCameraAcceptanceService(
        settings,
        database,
        benchmark_factory=(
            lambda _settings, _database:
            FakeBenchmark(camera_id)
        ),
        clock=lambda: next(moments),
    )
    try:
        prepared = service.prepare(
            camera_id
        )
        assert prepared["passed"] is True
        assert (
            prepared["baseline_segment"][
                "timing_source"
            ]
            == "NEXT_SEGMENT_BOUNDARY"
        )

        restarted = service.mark_restart(
            camera_id
        )
        restart_at = service._parse(
            restarted[
                "restart_completed_at"
            ]
        )
        add_post_restart_segment(
            database,
            camera_id,
            created_at=(
                restart_at
                + timedelta(minutes=6)
            ),
        )

        incomplete = service.verify(
            camera_id,
            live_confirmed=False,
            playback_confirmed=True,
        )
        assert incomplete["passed"] is False
        assert (
            "live_view_not_confirmed"
            in incomplete[
                "verification"
            ]["failures"]
        )

        passed = service.verify(
            camera_id,
            live_confirmed=True,
            playback_confirmed=True,
        )
        assert passed["passed"] is True
        assert (
            passed["verification"][
                "post_restart_segment"
            ]
            is not None
        )
    finally:
        database.close()
