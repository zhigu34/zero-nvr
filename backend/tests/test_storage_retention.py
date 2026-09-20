from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import (
    CameraGroup,
    CameraGroupMember,
    CameraStreamProfile,
)
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingProtection,
    RecordingSegment,
    RetentionPolicy,
)
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)
from app.modules.storage.retention import (
    LocalRetentionDeletionService,
    RetentionPlanner,
)
from app.modules.storage.service import StorageTargetService


RCLONE_CONFIG = """[archive]
type = webdav
url = https://example.invalid/dav
user = archive
pass = encrypted-by-zero-nvr
"""


def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key="retention-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'retention.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=tmp_path / "recordings",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    settings.recordings_dir.mkdir(parents=True, exist_ok=True)
    return settings, database


def seed_camera(
    settings: Settings,
    database: Database,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
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
        storage = StorageTargetService(settings)
        local = storage.create(
            session,
            target_type="local",
            role="recording",
            name="Local Recording",
            enabled=True,
            config={
                "path": str(settings.recordings_dir),
                "default_recording": True,
            },
            rclone_config=None,
        )
        remote = storage.create(
            session,
            target_type="rclone",
            role="archive",
            name="Cloud Archive",
            enabled=True,
            config={
                "remote": "archive",
                "base_path": "zero-nvr/archive",
                "default_archive": True,
            },
            rclone_config=RCLONE_CONFIG,
        )
        profile_id = session.scalar(
            select(CameraStreamProfile.id).where(
                CameraStreamProfile.camera_id == camera.id,
                CameraStreamProfile.adapter_profile_key
                == "manual-primary",
            )
        )
        assert profile_id is not None
        session.commit()
        return camera.id, profile_id, local.id, remote.id


def add_segment(
    database: Database,
    *,
    camera_id: uuid.UUID,
    profile_id: uuid.UUID,
    local_target_id: uuid.UUID,
    ended_at: datetime,
    reasons: list[str],
    object_name: str,
    size: int = 1024,
) -> tuple[uuid.UUID, uuid.UUID, Path]:
    started_at = ended_at - timedelta(seconds=10)
    object_path = f"retention/{object_name}.mp4"

    with database.session() as session:
        segment = RecordingSegment(
            camera_id=camera_id,
            stream_profile_id=profile_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=10_000,
            timing_status="FINAL",
            timing_source="RECOVERY",
            recording_reasons_json=reasons,
            size_bytes=size,
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
        location = RecordingLocation(
            recording_segment_id=segment.id,
            storage_target_id=local_target_id,
            object_path=object_path,
            state="AVAILABLE",
            size_bytes=size,
        )
        session.add(location)
        session.commit()
        segment_id = segment.id
        location_id = location.id

    path = Path(
        database.settings.recordings_dir
        if hasattr(database, "settings")
        else "/unused"
    )
    return segment_id, location_id, Path(object_path)


def write_local_file(
    settings: Settings,
    *,
    object_path: str,
    size: int = 1024,
) -> Path:
    path = settings.recordings_dir / object_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def add_explicit_retention(
    database: Database,
    *,
    camera_id: uuid.UUID,
    mode: str = "HARD",
    ordinary_days: int = 7,
    event_days: int = 30,
    manual_days: int = 90,
    require_archive: bool = True,
) -> uuid.UUID:
    with database.session() as session:
        policy = RetentionPolicy(
            name=f"Policy-{uuid.uuid4().hex[:8]}",
            scope_type="GLOBAL",
            scope_id=None,
            ordinary_keep_days=ordinary_days,
            event_keep_days=event_days,
            manual_keep_days=manual_days,
            mode=mode,
            require_archive_before_delete=require_archive,
            enabled=True,
        )
        session.add(policy)
        session.flush()
        recording = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )
        if recording is None:
            recording = RecordingPolicy(
                camera_id=camera_id,
                baseline_mode="continuous",
                enabled=True,
            )
            session.add(recording)
        recording.retention_policy_id = policy.id
        session.commit()
        return policy.id


def add_remote_available(
    database: Database,
    *,
    segment_id: uuid.UUID,
    remote_target_id: uuid.UUID,
    object_path: str,
    size: int = 1024,
) -> uuid.UUID:
    with database.session() as session:
        location = RecordingLocation(
            recording_segment_id=segment_id,
            storage_target_id=remote_target_id,
            object_path=object_path,
            state="AVAILABLE",
            size_bytes=size,
            verified_at=datetime.now(UTC),
        )
        session.add(location)
        session.commit()
        return location.id


def test_archive_gate_blocks_then_allows_expired_local_delete(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, local_id, remote_id = seed_camera(
            settings,
            database,
        )
        add_explicit_retention(
            database,
            camera_id=camera_id,
            ordinary_days=7,
            require_archive=True,
        )

        now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
        segment_id, location_id, relative = add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            local_target_id=local_id,
            ended_at=now - timedelta(days=10),
            reasons=["continuous"],
            object_name="ordinary-old",
        )

        with database.session() as session:
            location = session.get(RecordingLocation, location_id)
            assert location is not None
            blocked = RetentionPlanner.evaluate(
                session,
                location=location,
                now=now,
            )
            assert blocked.eligible_for_delete is False
            assert blocked.reason == "archive_required"
            assert blocked.archive_target_id == remote_id

        add_remote_available(
            database,
            segment_id=segment_id,
            remote_target_id=remote_id,
            object_path=relative.as_posix(),
        )

        with database.session() as session:
            location = session.get(RecordingLocation, location_id)
            assert location is not None
            allowed = RetentionPlanner.evaluate(
                session,
                location=location,
                now=now,
            )
            assert allowed.eligible_for_delete is True
            assert allowed.reason == "eligible"
            assert allowed.retention_class == "ordinary"
    finally:
        database.close()


def test_protection_wins_over_expiry_and_archive(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, local_id, remote_id = seed_camera(
            settings,
            database,
        )
        add_explicit_retention(
            database,
            camera_id=camera_id,
            ordinary_days=0,
            require_archive=True,
        )
        now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
        segment_id, location_id, relative = add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            local_target_id=local_id,
            ended_at=now - timedelta(days=1),
            reasons=["continuous"],
            object_name="protected",
        )
        add_remote_available(
            database,
            segment_id=segment_id,
            remote_target_id=remote_id,
            object_path=relative.as_posix(),
        )

        with database.session() as session:
            segment = session.get(RecordingSegment, segment_id)
            assert segment is not None
            session.add(
                RecordingProtection(
                    camera_id=camera_id,
                    started_at=segment.started_at
                    - timedelta(seconds=1),
                    ended_at=segment.ended_at
                    + timedelta(seconds=1),
                    reason="legal hold",
                    expires_at=None,
                )
            )
            session.commit()

        with database.session() as session:
            location = session.get(RecordingLocation, location_id)
            assert location is not None
            decision = RetentionPlanner.evaluate(
                session,
                location=location,
                now=now,
                pressure=True,
            )
            assert decision.eligible_for_delete is False
            assert decision.reason == "protected"
    finally:
        database.close()


def test_best_effort_pressure_can_expire_early_but_hard_cannot(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, local_id, remote_id = seed_camera(
            settings,
            database,
        )
        policy_id = add_explicit_retention(
            database,
            camera_id=camera_id,
            mode="BEST_EFFORT",
            ordinary_days=30,
            require_archive=True,
        )
        now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
        segment_id, location_id, relative = add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            local_target_id=local_id,
            ended_at=now - timedelta(days=1),
            reasons=["continuous"],
            object_name="pressure",
        )
        add_remote_available(
            database,
            segment_id=segment_id,
            remote_target_id=remote_id,
            object_path=relative.as_posix(),
        )

        with database.session() as session:
            location = session.get(RecordingLocation, location_id)
            assert location is not None
            normal = RetentionPlanner.evaluate(
                session,
                location=location,
                now=now,
                pressure=False,
            )
            assert normal.reason == "before_deadline"

            pressure = RetentionPlanner.evaluate(
                session,
                location=location,
                now=now,
                pressure=True,
            )
            assert pressure.eligible_for_delete is True
            assert pressure.pressure_override is True

            policy = session.get(RetentionPolicy, policy_id)
            assert policy is not None
            policy.mode = "HARD"
            session.commit()

        with database.session() as session:
            location = session.get(RecordingLocation, location_id)
            assert location is not None
            hard = RetentionPlanner.evaluate(
                session,
                location=location,
                now=now,
                pressure=True,
            )
            assert hard.eligible_for_delete is False
            assert hard.reason == "before_deadline"
    finally:
        database.close()


def test_manual_and_event_use_longer_retention_classes(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, local_id, _remote_id = seed_camera(
            settings,
            database,
        )
        add_explicit_retention(
            database,
            camera_id=camera_id,
            ordinary_days=1,
            event_days=10,
            manual_days=20,
            require_archive=False,
        )
        now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

        _, ordinary_location, _ = add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            local_target_id=local_id,
            ended_at=now - timedelta(days=5),
            reasons=["continuous"],
            object_name="ordinary",
        )
        _, event_location, _ = add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            local_target_id=local_id,
            ended_at=now - timedelta(days=5),
            reasons=["event"],
            object_name="event",
        )
        _, manual_location, _ = add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            local_target_id=local_id,
            ended_at=now - timedelta(days=15),
            reasons=["event", "manual"],
            object_name="manual",
        )

        with database.session() as session:
            ordinary = RetentionPlanner.evaluate(
                session,
                location=session.get(
                    RecordingLocation,
                    ordinary_location,
                ),
                now=now,
            )
            event = RetentionPlanner.evaluate(
                session,
                location=session.get(
                    RecordingLocation,
                    event_location,
                ),
                now=now,
            )
            manual = RetentionPlanner.evaluate(
                session,
                location=session.get(
                    RecordingLocation,
                    manual_location,
                ),
                now=now,
            )
            assert ordinary.retention_class == "ordinary"
            assert ordinary.eligible_for_delete is True
            assert event.retention_class == "event"
            assert event.reason == "before_deadline"
            assert manual.retention_class == "manual"
            assert manual.reason == "before_deadline"
    finally:
        database.close()


def test_policy_precedence_explicit_then_camera_then_nearest_group_then_global(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, _profile_id, _local_id, _remote_id = seed_camera(
            settings,
            database,
        )

        with database.session() as session:
            parent = CameraGroup(name="Building")
            child = CameraGroup(name="Floor 1")
            session.add_all([parent, child])
            session.flush()
            child.parent_id = parent.id
            session.add(
                CameraGroupMember(
                    camera_group_id=child.id,
                    camera_id=camera_id,
                )
            )

            global_policy = RetentionPolicy(
                name="Global",
                scope_type="GLOBAL",
                scope_id=None,
                ordinary_keep_days=1,
                event_keep_days=1,
                manual_keep_days=1,
                mode="HARD",
                require_archive_before_delete=False,
                enabled=True,
            )
            parent_policy = RetentionPolicy(
                name="Parent",
                scope_type="CAMERA_GROUP",
                scope_id=parent.id,
                ordinary_keep_days=2,
                event_keep_days=2,
                manual_keep_days=2,
                mode="HARD",
                require_archive_before_delete=False,
                enabled=True,
            )
            child_policy = RetentionPolicy(
                name="Child",
                scope_type="CAMERA_GROUP",
                scope_id=child.id,
                ordinary_keep_days=3,
                event_keep_days=3,
                manual_keep_days=3,
                mode="HARD",
                require_archive_before_delete=False,
                enabled=True,
            )
            session.add_all(
                [
                    global_policy,
                    parent_policy,
                    child_policy,
                ]
            )
            session.commit()
            child_policy_id = child_policy.id

        with database.session() as session:
            selected = RetentionPlanner.policy_for_camera(
                session,
                camera_id=camera_id,
            )
            assert selected is not None
            assert selected.id == child_policy_id

            camera_policy = RetentionPolicy(
                name="Camera",
                scope_type="CAMERA",
                scope_id=camera_id,
                ordinary_keep_days=4,
                event_keep_days=4,
                manual_keep_days=4,
                mode="HARD",
                require_archive_before_delete=False,
                enabled=True,
            )
            session.add(camera_policy)
            session.commit()
            camera_policy_id = camera_policy.id

        with database.session() as session:
            selected = RetentionPlanner.policy_for_camera(
                session,
                camera_id=camera_id,
            )
            assert selected is not None
            assert selected.id == camera_policy_id

            explicit = RetentionPolicy(
                name="Explicit",
                scope_type="GLOBAL",
                scope_id=None,
                ordinary_keep_days=5,
                event_keep_days=5,
                manual_keep_days=5,
                mode="HARD",
                require_archive_before_delete=False,
                enabled=True,
            )
            session.add(explicit)
            session.flush()
            recording = session.scalar(
                select(RecordingPolicy).where(
                    RecordingPolicy.camera_id == camera_id
                )
            )
            if recording is None:
                recording = RecordingPolicy(
                    camera_id=camera_id,
                    baseline_mode="continuous",
                    enabled=True,
                )
                session.add(recording)
            recording.retention_policy_id = explicit.id
            session.commit()
            explicit_id = explicit.id

        with database.session() as session:
            selected = RetentionPlanner.policy_for_camera(
                session,
                camera_id=camera_id,
            )
            assert selected is not None
            assert selected.id == explicit_id
    finally:
        database.close()


def test_local_delete_runs_only_after_planner_allows_it(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, profile_id, local_id, _remote_id = seed_camera(
            settings,
            database,
        )
        add_explicit_retention(
            database,
            camera_id=camera_id,
            ordinary_days=0,
            require_archive=False,
        )
        now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
        _segment_id, location_id, relative = add_segment(
            database,
            camera_id=camera_id,
            profile_id=profile_id,
            local_target_id=local_id,
            ended_at=now - timedelta(days=1),
            reasons=["continuous"],
            object_name="delete-me",
        )
        source = write_local_file(
            settings,
            object_path=relative.as_posix(),
        )
        assert source.is_file()

        result = LocalRetentionDeletionService.execute(
            database,
            location_id=location_id,
            now=now,
        )
        assert result.deleted is True
        assert not source.exists()

        with database.session() as session:
            location = session.get(
                RecordingLocation,
                location_id,
            )
            assert location is not None
            assert location.state == "DELETED"
            assert location.deleted_at is not None
            assert location.last_error is None
    finally:
        database.close()
