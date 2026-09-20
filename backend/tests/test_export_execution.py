from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.integrations.ffmpeg import FfmpegExportResult
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.exports.execution import ExportExecutionService
from app.modules.exports.models import ExportJob
from app.modules.recordings.models import RecordingSegment
from app.modules.storage.models import RecordingLocation, StorageTarget


class FakeAdapter:
    calls = 0

    def __init__(self, **_kwargs) -> None:
        pass

    def render(self, *, clips, output_path, codec_mode):
        self.__class__.calls += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"rendered")
        return FfmpegExportResult(
            output_path=output_path,
            size_bytes=len(b"rendered"),
            duration_ms=4500,
            codec_mode="copy",
        )


def make_database(tmp_path: Path):
    settings = Settings(
        secret_key="export-execution-test-secret-key-32-bytes",
        database_url=f"sqlite:///{tmp_path / 'execution.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed(settings: Settings, database: Database, tmp_path: Path):
    root = tmp_path / "recordings"
    root.mkdir()
    media = root / "one.mp4"
    media.write_bytes(b"media")

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
            name="Local",
            type="local",
            role="recording",
            enabled=True,
            config_json={"path": str(root)},
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

        start = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
        segment = RecordingSegment(
            camera_id=camera.id,
            stream_profile_id=profile_id,
            started_at=start,
            ended_at=start + timedelta(seconds=5),
            duration_ms=5000,
            timing_status="FINAL",
            timing_source="RECOVERY",
            recording_reasons_json=["continuous"],
            size_bytes=media.stat().st_size,
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
                object_path="one.mp4",
                state="AVAILABLE",
                size_bytes=media.stat().st_size,
            )
        )

        job = ExportJob(
            camera_id=camera.id,
            requested_by=None,
            requested_start_at=start,
            requested_end_at=start + timedelta(seconds=5),
            requested_duration_ms=5000,
            format="mp4",
            codec_mode="auto",
            gap_policy="skip",
            state="PENDING",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            metadata_json={},
        )
        session.add(job)
        session.commit()
        return job.id


def test_execution_marks_completed_and_is_idempotent(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        export_id = seed(settings, database, tmp_path)
        FakeAdapter.calls = 0
        service = ExportExecutionService(
            settings,
            adapter_factory=FakeAdapter,
        )

        result = service.execute(
            database,
            export_id=export_id,
        )
        assert result.state == "COMPLETED"
        assert result.rendered is True
        assert FakeAdapter.calls == 1

        repeated = service.execute(
            database,
            export_id=export_id,
        )
        assert repeated.state == "COMPLETED"
        assert repeated.rendered is False
        assert FakeAdapter.calls == 1

        with database.session() as session:
            job = session.get(ExportJob, export_id)
            assert job is not None
            assert job.state == "COMPLETED"
            assert job.actual_duration_ms == 4500
            assert job.size_bytes == len(b"rendered")
            assert (
                job.metadata_json["effective_codec_mode"]
                == "copy"
            )
            assert Path(job.output_path).is_file()
    finally:
        database.close()


def test_gap_failure_marks_job_failed_without_running_ffmpeg(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        export_id = seed(settings, database, tmp_path)
        with database.session() as session:
            job = session.get(ExportJob, export_id)
            assert job is not None
            job.requested_end_at = (
                job.requested_end_at
                + timedelta(seconds=5)
            )
            job.requested_duration_ms = 10_000
            job.gap_policy = "fail"
            session.commit()

        FakeAdapter.calls = 0
        result = ExportExecutionService(
            settings,
            adapter_factory=FakeAdapter,
        ).execute(
            database,
            export_id=export_id,
        )

        assert result.state == "FAILED"
        assert result.rendered is False
        assert FakeAdapter.calls == 0
        with database.session() as session:
            job = session.get(ExportJob, export_id)
            assert job is not None
            assert job.error_code == "export_range_has_gaps"
    finally:
        database.close()
