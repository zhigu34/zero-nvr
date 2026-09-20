from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.core.errors import ApiError
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.exports.plan import ExportPlanResolver
from app.modules.recordings.models import RecordingSegment
from app.modules.storage.models import RecordingLocation, StorageTarget


def make_database(tmp_path: Path):
    settings = Settings(
        secret_key="export-plan-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'export-plan.db'}",
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
    tmp_path: Path,
):
    root = tmp_path / "recordings"
    root.mkdir()

    with database.session() as session:
        camera = CameraService(
            settings
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
        target = StorageTarget(
            name="Local Recording",
            type="local",
            role="recording",
            enabled=True,
            config_json={"path": str(root)},
        )
        session.add(target)
        session.flush()
        profile_id = session.scalar(
            select(CameraStreamProfile.id).where(
                CameraStreamProfile.camera_id
                == camera.id,
                CameraStreamProfile.adapter_profile_key
                == "manual-primary",
            )
        )
        assert profile_id is not None
        session.commit()
        return camera.id, profile_id, target.id, root


def add_segment(
    database: Database,
    *,
    camera_id,
    profile_id,
    target_id,
    root: Path,
    start: datetime,
    duration: int,
    name: str,
    codec: str = "h264",
):
    path = root / name
    path.write_bytes(b"x")
    with database.session() as session:
        segment = RecordingSegment(
            camera_id=camera_id,
            stream_profile_id=profile_id,
            started_at=start,
            ended_at=start + timedelta(seconds=duration),
            duration_ms=duration * 1000,
            timing_status="FINAL",
            timing_source="RECOVERY",
            recording_reasons_json=["continuous"],
            size_bytes=1,
            codec=codec,
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
                storage_target_id=target_id,
                object_path=name,
                state="AVAILABLE",
                size_bytes=1,
            )
        )
        session.commit()


def test_skip_gaps_selects_only_real_media(tmp_path: Path) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, target_id, root = seed(
            settings,
            database,
            tmp_path,
        )
        base = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
        add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            target_id=target_id,
            root=root,
            start=base,
            duration=10,
            name="one.mp4",
        )
        add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            target_id=target_id,
            root=root,
            start=base + timedelta(seconds=20),
            duration=10,
            name="two.mp4",
        )

        with database.session() as session:
            plan = ExportPlanResolver.build(
                session,
                camera_id=camera_id,
                start_at=base + timedelta(seconds=5),
                end_at=base + timedelta(seconds=25),
                gap_policy="skip",
            )

        assert plan.has_gaps is True
        assert plan.actual_duration_ms == 10_000
        assert len(plan.items) == 2
        assert plan.items[0].inpoint_seconds == 5
        assert plan.items[0].outpoint_seconds == 10
        assert plan.items[1].inpoint_seconds == 0
        assert plan.items[1].outpoint_seconds == 5
    finally:
        database.close()


def test_fail_gap_policy_rejects_missing_interval(tmp_path: Path) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, target_id, root = seed(
            settings,
            database,
            tmp_path,
        )
        base = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
        add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            target_id=target_id,
            root=root,
            start=base,
            duration=5,
            name="one.mp4",
        )

        with database.session() as session:
            with pytest.raises(ApiError) as captured:
                ExportPlanResolver.build(
                    session,
                    camera_id=camera_id,
                    start_at=base,
                    end_at=base + timedelta(seconds=10),
                    gap_policy="fail",
                )
        assert captured.value.code == "export_range_has_gaps"
    finally:
        database.close()
