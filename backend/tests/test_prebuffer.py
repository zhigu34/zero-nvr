from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.recordings.prebuffer import (
    PrebufferFragment,
    PrebufferFragmentTracker,
    PrebufferPromotionService,
)
from app.modules.storage.models import RecordingLocation, StorageTarget


def fragment(
    *,
    camera_id: uuid.UUID | None = None,
    profile_id: uuid.UUID | None = None,
    continuity_id: uuid.UUID | None = None,
    path: str,
    start: float,
    duration: float,
    size: int,
) -> PrebufferFragment:
    from datetime import timedelta

    started = datetime.fromtimestamp(start, tz=UTC)
    return PrebufferFragment(
        camera_id=camera_id or uuid.uuid4(),
        profile_id=profile_id or uuid.uuid4(),
        continuity_id=continuity_id,
        vhost="__defaultVhost__",
        app="zero-nvr",
        stream="profile-test",
        file_path=Path(path),
        started_at=started,
        ended_at=started + timedelta(seconds=duration),
        duration_ms=int(duration * 1000),
        size_bytes=size,
    )


def test_same_continuity_normalizes_previous_fragment_boundary() -> None:
    tracker = PrebufferFragmentTracker()
    camera_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    continuity_id = uuid.uuid4()

    first = tracker.observe(
        camera_id=camera_id,
        profile_id=profile_id,
        continuity_id=continuity_id,
        vhost="__defaultVhost__",
        app="zero-nvr",
        stream="profile-test",
        file_path="/prebuffer/one.mp4",
        start_time_epoch=1000,
        duration_seconds=8,
        size_bytes=100,
    )
    second = tracker.observe(
        camera_id=camera_id,
        profile_id=profile_id,
        continuity_id=continuity_id,
        vhost="__defaultVhost__",
        app="zero-nvr",
        stream="profile-test",
        file_path="/prebuffer/two.mp4",
        start_time_epoch=1009,
        duration_seconds=8,
        size_bytes=100,
    )

    items = tracker.fragments_for_camera(camera_id)
    assert len(items) == 2
    assert items[0].started_at == datetime.fromtimestamp(1001, UTC)
    assert items[0].ended_at == datetime.fromtimestamp(1009, UTC)
    assert items[1] == second
    assert first.file_path == Path("/prebuffer/one.mp4")


def test_new_continuity_does_not_rewrite_previous_fragment() -> None:
    tracker = PrebufferFragmentTracker()
    camera_id = uuid.uuid4()
    profile_id = uuid.uuid4()

    tracker.observe(
        camera_id=camera_id,
        profile_id=profile_id,
        continuity_id=uuid.uuid4(),
        vhost="__defaultVhost__",
        app="zero-nvr",
        stream="profile-test",
        file_path="/prebuffer/one.mp4",
        start_time_epoch=2000,
        duration_seconds=8,
        size_bytes=100,
    )
    tracker.observe(
        camera_id=camera_id,
        profile_id=profile_id,
        continuity_id=uuid.uuid4(),
        vhost="__defaultVhost__",
        app="zero-nvr",
        stream="profile-test",
        file_path="/prebuffer/two.mp4",
        start_time_epoch=2030,
        duration_seconds=8,
        size_bytes=100,
    )

    items = tracker.fragments_for_camera(camera_id)
    assert items[0].started_at == datetime.fromtimestamp(2000, UTC)
    assert items[0].ended_at == datetime.fromtimestamp(2008, UTC)


def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key="prebuffer-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'prebuffer.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed(
    settings: Settings,
    database: Database,
) -> tuple[uuid.UUID, uuid.UUID, StorageTarget]:
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
            config_json={"path": str(settings.recordings_dir)},
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
        return camera.id, profile_id, target


def test_atomic_promotion_is_idempotent_even_after_source_disappears(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    settings.prebuffer_dir.mkdir(parents=True)
    settings.recordings_dir.mkdir(parents=True)

    try:
        camera_id, profile_id, target = seed(settings, database)
        source = settings.prebuffer_dir / "record/zero-nvr/profile-test/one.mp4"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"x" * 4096)

        item = fragment(
            camera_id=camera_id,
            profile_id=profile_id,
            path=str(source),
            start=3000,
            duration=5,
            size=4096,
        )

        receipt = PrebufferPromotionService.prepare(
            fragment=item,
            prebuffer_root=settings.prebuffer_dir,
            storage_target_id=target.id,
            target_root=settings.recordings_dir,
        )
        assert receipt.destination.is_file()
        assert not receipt.destination.with_name(
            receipt.destination.name + ".partial"
        ).exists()

        source.unlink()

        retry = PrebufferPromotionService.prepare(
            fragment=item,
            prebuffer_root=settings.prebuffer_dir,
            storage_target_id=target.id,
            target_root=settings.recordings_dir,
        )
        assert retry.destination == receipt.destination
        assert retry.size_bytes == 4096

        with database.session() as session:
            segment = PrebufferPromotionService.commit(
                session,
                receipt=retry,
            )
            session.commit()
            segment_id = segment.id

        with database.session() as session:
            same = PrebufferPromotionService.commit(
                session,
                receipt=retry,
            )
            session.commit()
            assert same.id == segment_id
            locations = list(
                session.scalars(
                    select(RecordingLocation).where(
                        RecordingLocation.recording_segment_id
                        == segment_id
                    )
                )
            )
            assert len(locations) == 1
    finally:
        database.close()
