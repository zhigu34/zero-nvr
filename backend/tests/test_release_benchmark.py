from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingPolicy
from app.modules.storage.models import StorageTarget
from app.modules.system.benchmark import (
    ReleaseBenchmarkService,
)


class FakeZlm:
    offline_streams: set[str] = set()
    inactive_streams: set[str] = set()

    def __init__(self, _settings) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def is_media_online(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool:
        return stream not in self.offline_streams

    def is_mp4_recording(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool:
        return stream not in self.inactive_streams


def make_database(
    tmp_path: Path,
) -> tuple[Settings, Database]:
    recordings = tmp_path / "recordings"
    recordings.mkdir()

    settings = Settings(
        secret_key=(
            "release-benchmark-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'benchmark.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=recordings,
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    return settings, database


def seed_recording_cameras(
    settings: Settings,
    database: Database,
    *,
    count: int,
) -> list[str]:
    streams: list[str] = []

    with database.session() as session:
        session.add(
            StorageTarget(
                name="Benchmark local",
                type="local",
                role="recording",
                enabled=True,
                config_json={
                    "path": str(
                        settings.recordings_dir
                    ),
                    "default_recording": True,
                },
            )
        )
        service = CameraService(settings)
        for index in range(count):
            camera = (
                service.create_manual_rtsp_camera(
                    session,
                    name=f"Camera {index + 1}",
                    location=None,
                    storage_label=None,
                    primary_name="Main",
                    primary_url=(
                        "rtsp://camera.local/"
                        f"{index + 1}"
                    ),
                    secondary_name=None,
                    secondary_url=None,
                )
            )
            session.add(
                RecordingPolicy(
                    camera_id=camera.id,
                    baseline_mode="continuous",
                    schedule_json={},
                    schedule_timezone=None,
                    event_recording_enabled=False,
                    event_filter_json={},
                    segment_target_seconds=300,
                    pre_roll_seconds=10,
                    post_roll_seconds=10,
                    storage_target_id=None,
                    retention_policy_id=None,
                    enabled=True,
                )
            )
            record_binding = next(
                item
                for item in camera.stream_bindings
                if item.purpose == "RECORD"
            )
            streams.append(
                "profile-"
                + record_binding.stream_profile_id.hex
            )
        session.commit()

    return streams


def test_release_benchmark_passes_when_target_recorders_are_online(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        seed_recording_cameras(
            settings,
            database,
            count=2,
        )
        FakeZlm.offline_streams = set()
        FakeZlm.inactive_streams = set()

        result = ReleaseBenchmarkService(
            settings,
            database,
            zlm_factory=FakeZlm,
        ).collect(
            expected_cameras=2
        )

        assert result.passed is True
        assert result.enabled_cameras == 2
        assert (
            result.recording_expected_cameras
            == 2
        )
        assert result.record_streams_online == 2
        assert result.recorders_active == 2
        assert result.failures == ()
    finally:
        database.close()


def test_release_benchmark_reports_offline_and_capacity_failures(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        streams = seed_recording_cameras(
            settings,
            database,
            count=2,
        )
        FakeZlm.offline_streams = {
            streams[0]
        }
        FakeZlm.inactive_streams = set()

        result = ReleaseBenchmarkService(
            settings,
            database,
            zlm_factory=FakeZlm,
        ).collect(
            expected_cameras=3
        )

        assert result.passed is False
        assert result.enabled_cameras == 2
        assert result.record_streams_online == 1
        assert result.recorders_active == 1
        assert (
            "enabled_camera_count_below_target"
            in result.failures
        )
        assert (
            "record_stream_online_count_below_target"
            in result.failures
        )
        assert (
            "active_recorder_count_below_target"
            in result.failures
        )
    finally:
        database.close()
