from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import cli
from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
)
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)
from app.modules.system.benchmark import (
    CameraBenchmarkStatus,
    ReleaseBenchmarkStatus,
)
from app.modules.system.health import (
    HealthComponent,
    ProductHealth,
)
from app.modules.system.soak import (
    ReleaseSoakService,
)


class FakeBenchmark:
    status: ReleaseBenchmarkStatus

    def __init__(
        self,
        _settings,
        _database,
    ) -> None:
        pass

    def collect(
        self,
        *,
        expected_cameras: int,
    ) -> ReleaseBenchmarkStatus:
        return self.status


class FakeHealth:
    health: ProductHealth

    def __init__(
        self,
        _settings,
        _database,
    ) -> None:
        pass

    def collect(self) -> ProductHealth:
        return self.health


def make_database(
    tmp_path: Path,
) -> tuple[Settings, Database]:
    recordings = tmp_path / "recordings"
    recordings.mkdir()

    settings = Settings(
        secret_key=(
            "release-soak-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'soak.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=recordings,
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    return settings, database


def healthy() -> ProductHealth:
    return ProductHealth(
        status="OK",
        components={
            name: HealthComponent(
                status="OK"
            )
            for name in (
                "database",
                "worker",
                "zlmediakit",
                "storage",
            )
        },
    )


def seed_persistent_camera(
    settings: Settings,
    database: Database,
) -> tuple[str, object, object]:
    with database.session() as session:
        target = StorageTarget(
            name="Local",
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
        session.add(target)
        camera = CameraService(
            settings
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
        session.commit()
        return camera.name, camera.id, target.id


def runtime_for(
    camera_name: str,
    camera_id,
) -> ReleaseBenchmarkStatus:
    camera = CameraBenchmarkStatus(
        camera_id=camera_id,
        name=camera_name,
        desired_mode="persistent",
        stream_online=True,
        recording_active=True,
        error=None,
    )
    return ReleaseBenchmarkStatus(
        expected_cameras=1,
        enabled_cameras=1,
        recording_expected_cameras=1,
        record_streams_online=1,
        recorders_active=1,
        passed=True,
        failures=(),
        cameras=(camera,),
    )


def test_soak_requires_persistent_media_progress(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path
    )
    try:
        name, camera_id, target_id = (
            seed_persistent_camera(
                settings,
                database,
            )
        )
        FakeBenchmark.status = runtime_for(
            name,
            camera_id,
        )
        FakeHealth.health = healthy()
        since = datetime.now(UTC) - timedelta(
            minutes=10
        )

        service = ReleaseSoakService(
            settings,
            database,
            benchmark_factory=FakeBenchmark,
            health_factory=FakeHealth,
        )

        before = service.collect(
            expected_cameras=1,
            since=since,
            require_progress=True,
        )
        assert before.passed is False
        assert (
            "persistent_recording_progress_failed"
            in before.failures
        )

        with database.session() as session:
            segment = RecordingSegment(
                camera_id=camera_id,
                stream_profile_id=None,
                started_at=(
                    datetime.now(UTC)
                    - timedelta(minutes=2)
                ),
                ended_at=(
                    datetime.now(UTC)
                    - timedelta(minutes=1)
                ),
                duration_ms=60_000,
                timing_status="FINAL",
                timing_source="RECOVERY",
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
            )
            session.add(segment)
            session.flush()
            session.add(
                RecordingLocation(
                    recording_segment_id=segment.id,
                    storage_target_id=target_id,
                    object_path=(
                        "record/zero-nvr/test.mp4"
                    ),
                    state="AVAILABLE",
                    size_bytes=1024,
                )
            )
            session.commit()

        after = service.collect(
            expected_cameras=1,
            since=since,
            require_progress=True,
        )
        assert after.passed is True
        assert (
            after.persistent_progress[0]
            .segments_since_start
            == 1
        )
        assert (
            after.persistent_progress[0]
            .available_local_segments_since_start
            == 1
        )
        assert (
            after.persistent_progress[0]
            .bytes_since_start
            == 1024
        )
    finally:
        database.close()


def test_soak_reports_required_health_failure_without_early_progress_gate(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path
    )
    try:
        name, camera_id, _target_id = (
            seed_persistent_camera(
                settings,
                database,
            )
        )
        FakeBenchmark.status = runtime_for(
            name,
            camera_id,
        )
        FakeHealth.health = ProductHealth(
            status="DEGRADED",
            components={
                "database": HealthComponent(
                    status="OK"
                ),
                "worker": HealthComponent(
                    status="ERROR",
                    message=(
                        "worker_heartbeat_stale"
                    ),
                ),
                "zlmediakit": HealthComponent(
                    status="OK"
                ),
                "storage": HealthComponent(
                    status="OK"
                ),
            },
        )

        result = ReleaseSoakService(
            settings,
            database,
            benchmark_factory=FakeBenchmark,
            health_factory=FakeHealth,
        ).collect(
            expected_cameras=1,
            since=datetime.now(UTC),
            require_progress=False,
        )

        assert result.passed is False
        assert (
            "health_worker_error"
            in result.failures
        )
        assert (
            "persistent_recording_progress_failed"
            not in result.failures
        )
    finally:
        database.close()

def test_soak_database_status_reports_sqlite_wal(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    database.initialize_runtime()
    try:
        status = cli._soak_database_status(
            database
        )
        assert status["backend"] == "sqlite"
        assert isinstance(
            status["sqlite_wal_bytes"],
            int,
        )
    finally:
        database.close()
