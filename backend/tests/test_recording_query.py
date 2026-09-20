from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingSegment
from app.modules.recordings.query import RecordingCatalogQueryService


def make_database(tmp_path: Path):
    settings = Settings(
        secret_key="query-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'query.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def test_recording_catalog_cursor_has_no_duplicates(
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
            profile_id = session.scalar(
                select(CameraStreamProfile.id).where(
                    CameraStreamProfile.camera_id == camera.id,
                    CameraStreamProfile.adapter_profile_key == "manual-primary",
                )
            )
            assert profile_id is not None

            base = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
            ids = []
            for index in range(5):
                started = base + timedelta(minutes=index)
                segment = RecordingSegment(
                    camera_id=camera.id,
                    stream_profile_id=profile_id,
                    started_at=started,
                    ended_at=started + timedelta(minutes=1),
                    duration_ms=60_000,
                    timing_status="FINAL",
                    timing_source="RECOVERY",
                    recording_reasons_json=["continuous"],
                    size_bytes=100 + index,
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
                ids.append(segment.id)
            session.commit()
            camera_id = camera.id

        with database.session() as session:
            first = RecordingCatalogQueryService.list_camera(
                session,
                camera_id=camera_id,
                start_at=None,
                end_at=None,
                cursor=None,
                limit=2,
            )
            assert len(first.items) == 2
            assert first.next_cursor is not None

            second = RecordingCatalogQueryService.list_camera(
                session,
                camera_id=camera_id,
                start_at=None,
                end_at=None,
                cursor=first.next_cursor,
                limit=2,
            )
            assert len(second.items) == 2
            assert second.next_cursor is not None

            third = RecordingCatalogQueryService.list_camera(
                session,
                camera_id=camera_id,
                start_at=None,
                end_at=None,
                cursor=second.next_cursor,
                limit=2,
            )
            assert len(third.items) == 1
            assert third.next_cursor is None

        seen = [
            item.id
            for page in (first, second, third)
            for item in page.items
        ]
        assert len(seen) == 5
        assert len(set(seen)) == 5
        assert seen == list(reversed(ids))
    finally:
        database.close()
