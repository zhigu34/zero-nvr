from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from huey import crontab
from typing import Any

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.modules.cameras.media_runtime import CameraMediaRuntimeService
from app.modules.cameras.models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
)
from app.modules.recordings.models import RecordingPolicy
from app.modules.recordings.policy import RecordingPolicyService
from app.modules.recordings.prebuffer import (
    PrebufferFragment,
    PrebufferPromotionService,
)
from app.modules.recordings.runtime import RecordingRuntimeService
from app.modules.recordings.triggers import RecordingTriggerService
from app.modules.storage.archive import ArchiveLifecycleService
from app.modules.storage.retention import (
    LocalRetentionDeletionService,
    RetentionPlanner,
)
from app.modules.storage.models import RecordingLocation
from app.modules.storage.recording_resolver import RecordingStorageResolver

from .queue import huey


_ZLM_FILENAME = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-"
    r"(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})"
    r"(?:-\d+)?\.mp4$"
)


def _fragment(
    *,
    camera_id: str,
    profile_id: str,
    continuity_id: str | None,
    vhost: str,
    app: str,
    stream: str,
    file_path: str,
    started_at_epoch: float,
    duration_seconds: float,
    size_bytes: int,
) -> PrebufferFragment:
    started_at = datetime.fromtimestamp(
        started_at_epoch,
        tz=UTC,
    )
    duration_ms = max(
        1,
        int(round(duration_seconds * 1000)),
    )
    from datetime import timedelta

    return PrebufferFragment(
        camera_id=uuid.UUID(camera_id),
        profile_id=uuid.UUID(profile_id),
        continuity_id=(
            uuid.UUID(continuity_id)
            if continuity_id is not None
            else None
        ),
        vhost=vhost,
        app=app,
        stream=stream,
        file_path=Path(file_path),
        started_at=started_at,
        ended_at=started_at + timedelta(
            milliseconds=duration_ms
        ),
        duration_ms=duration_ms,
        size_bytes=size_bytes,
    )


def _database(settings: Settings) -> Database:
    database = Database(settings)
    database.initialize_runtime()
    return database


def _promotion_target(
    database: Database,
    fragment: PrebufferFragment,
) -> tuple[uuid.UUID, Path] | None:
    with database.session() as session:
        required = RecordingTriggerService.overlaps_fragment(
            session,
            camera_id=fragment.camera_id,
            started_at=fragment.started_at,
            ended_at=fragment.ended_at,
        )
        if not required:
            session.commit()
            return None

        target = RecordingStorageResolver.local_target_for_camera(
            session,
            camera_id=fragment.camera_id,
        )
        target_id = target.target.id
        target_root = target.root
        session.commit()
        return target_id, target_root


def _destination_object_path(
    *,
    settings: Settings,
    fragment: PrebufferFragment,
    target_root: Path,
) -> str:
    source = fragment.file_path.resolve()
    relative = source.relative_to(
        settings.prebuffer_dir.resolve()
    )
    return (
        target_root.resolve()
        / "event"
        / relative
    ).relative_to(target_root.resolve()).as_posix()


def _canonical_available(
    database: Database,
    *,
    storage_target_id: uuid.UUID,
    object_path: str,
) -> bool:
    with database.session() as session:
        result = session.scalar(
            select(RecordingLocation.id).where(
                RecordingLocation.storage_target_id
                == storage_target_id,
                RecordingLocation.object_path
                == object_path,
                RecordingLocation.state == "AVAILABLE",
            )
        )
        session.commit()
        return result is not None


def _promote(
    settings: Settings,
    database: Database,
    fragment: PrebufferFragment,
) -> str | None:
    target = _promotion_target(database, fragment)
    if target is None:
        return None

    storage_target_id, target_root = target
    receipt = PrebufferPromotionService.prepare(
        fragment=fragment,
        prebuffer_root=settings.prebuffer_dir,
        storage_target_id=storage_target_id,
        target_root=target_root,
    )

    with database.session() as session:
        try:
            segment = PrebufferPromotionService.commit(
                session,
                receipt=receipt,
            )
            session.commit()
            return str(segment.id)
        except Exception:
            session.rollback()
            raise


@huey.task(retries=3, retry_delay=10)
def promote_prebuffer_fragment(
    camera_id: str,
    profile_id: str,
    continuity_id: str | None,
    vhost: str,
    app: str,
    stream: str,
    file_path: str,
    started_at_epoch: float,
    duration_seconds: float,
    size_bytes: int,
) -> str | None:
    settings = Settings()
    database = _database(settings)
    try:
        return _promote(
            settings,
            database,
            _fragment(
                camera_id=camera_id,
                profile_id=profile_id,
                continuity_id=continuity_id,
                vhost=vhost,
                app=app,
                stream=stream,
                file_path=file_path,
                started_at_epoch=started_at_epoch,
                duration_seconds=duration_seconds,
                size_bytes=size_bytes,
            ),
        )
    finally:
        database.close()


@huey.task(retries=3, retry_delay=30)
def gc_prebuffer_fragment(
    camera_id: str,
    profile_id: str,
    continuity_id: str | None,
    vhost: str,
    app: str,
    stream: str,
    file_path: str,
    started_at_epoch: float,
    duration_seconds: float,
    size_bytes: int,
) -> bool:
    settings = Settings()
    fragment = _fragment(
        camera_id=camera_id,
        profile_id=profile_id,
        continuity_id=continuity_id,
        vhost=vhost,
        app=app,
        stream=stream,
        file_path=file_path,
        started_at_epoch=started_at_epoch,
        duration_seconds=duration_seconds,
        size_bytes=size_bytes,
    )
    source = fragment.file_path.resolve(strict=False)
    if not source.exists():
        return True

    database = _database(settings)
    try:
        with database.session() as session:
            required = RecordingTriggerService.overlaps_fragment(
                session,
                camera_id=fragment.camera_id,
                started_at=fragment.started_at,
                ended_at=fragment.ended_at,
            )
            target = None
            if required:
                target = RecordingStorageResolver.local_target_for_camera(
                    session,
                    camera_id=fragment.camera_id,
                )
                target_id = target.target.id
                target_root = target.root
            session.commit()

        if required:
            assert target is not None
            object_path = _destination_object_path(
                settings=settings,
                fragment=fragment,
                target_root=target_root,
            )
            if not _canonical_available(
                database,
                storage_target_id=target_id,
                object_path=object_path,
            ):
                # The trigger still needs this fragment and promotion has not
                # become canonical yet. Retry instead of losing pre-roll.
                raise RuntimeError(
                    "required prebuffer fragment is not safely promoted"
                )

        try:
            source.relative_to(settings.prebuffer_dir.resolve())
        except ValueError:
            return False

        source.unlink(missing_ok=True)
        return True
    finally:
        database.close()


def _path_start(path: Path) -> datetime | None:
    match = _ZLM_FILENAME.match(path.name)
    if match is None:
        return None
    return datetime.fromisoformat(
        f"{match.group('date')}T"
        f"{match.group('h')}:{match.group('m')}:{match.group('s')}+00:00"
    )


def _probe_duration(path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload: dict[str, Any] = json.loads(completed.stdout)
    duration = float(
        (payload.get("format") or {}).get("duration") or 0
    )
    if duration <= 0:
        raise RuntimeError("prebuffer fragment has invalid duration")
    return duration


@huey.task(retries=2, retry_delay=15)
def reconcile_camera_prebuffer(camera_id: str) -> int:
    """Recover/promote finalized tmpfs fragments from DB trigger facts.

    This is used when a trigger is created/closed and after control-plane
    recovery. ffprobe is intentionally limited to this reconciliation path,
    not the normal finalized-hook path.
    """

    settings = Settings()
    database = _database(settings)
    camera_uuid = uuid.UUID(camera_id)

    try:
        with database.session() as session:
            binding = session.scalar(
                select(CameraStreamBinding).where(
                    CameraStreamBinding.camera_id == camera_uuid,
                    CameraStreamBinding.purpose == "RECORD",
                )
            )
            if binding is None:
                session.commit()
                return 0

            profile = session.get(
                CameraStreamProfile,
                binding.stream_profile_id,
            )
            if profile is None:
                session.commit()
                return 0

            profile_id = profile.id
            stream = f"profile-{profile.id.hex}"
            session.commit()

        root = settings.prebuffer_dir.resolve()
        if not root.is_dir():
            return 0

        promoted = 0
        for path in root.rglob("*.mp4"):
            if not path.is_file() or path.name.startswith("."):
                continue
            if stream not in path.parts:
                continue

            started_at = _path_start(path)
            if started_at is None:
                continue
            duration = _probe_duration(path)
            fragment = _fragment(
                camera_id=str(camera_uuid),
                profile_id=str(profile_id),
                continuity_id=None,
                vhost="__defaultVhost__",
                app="zero-nvr",
                stream=stream,
                file_path=str(path),
                started_at_epoch=started_at.timestamp(),
                duration_seconds=duration,
                size_bytes=path.stat().st_size,
            )
            if _promote(settings, database, fragment) is not None:
                promoted += 1
        return promoted
    finally:
        database.close()



@huey.task(retries=3, retry_delay=15)
def reconcile_recording_policy_boundary(
    policy_id: str,
    policy_version: str,
) -> bool:
    """Apply one persisted weekly schedule boundary and schedule the next."""

    settings = Settings()
    database = _database(settings)
    policy_uuid = uuid.UUID(policy_id)
    now = datetime.now(UTC)

    try:
        with database.session() as session:
            policy = session.get(RecordingPolicy, policy_uuid)
            if (
                policy is None
                or policy.updated_at.isoformat() != policy_version
                or not policy.enabled
                or policy.baseline_mode != "schedule"
            ):
                session.commit()
                return False

            camera = session.get(Camera, policy.camera_id)
            if camera is None:
                session.commit()
                return False

            media_runtime = CameraMediaRuntimeService(settings)
            desired_streams = media_runtime.desired_streams(
                session,
                camera=camera,
            )
            desired_recorder = RecordingRuntimeService.desired(
                session,
                settings=settings,
                camera_id=policy.camera_id,
                at=now,
            )
            if desired_recorder is None:
                record_streams = []
            else:
                record_streams = [
                    item
                    for item in desired_streams
                    if item.profile_id == desired_recorder.profile_id
                ]

            next_boundary = RecordingPolicyService.next_baseline_transition(
                policy,
                after=now,
            )
            current_version = policy.updated_at.isoformat()
            session.commit()

        if (
            desired_recorder is not None
            and desired_recorder.mode != "off"
        ):
            media_runtime.ensure_streams(record_streams)

        RecordingRuntimeService(settings).reconcile(
            desired_recorder,
            force_reconfigure=True,
        )

        if next_boundary is not None:
            reconcile_recording_policy_boundary.schedule(
                args=(policy_id, current_version),
                eta=next_boundary,
            )
        return True
    finally:
        database.close()



@huey.task(retries=3, retry_delay=60)
def archive_recording_segment(
    segment_id: str,
    target_id: str,
) -> str:
    """Archive one immutable recording object through rclone.

    Only stable ids enter the queue. Secret rclone configuration is resolved
    inside the worker at execution time.
    """

    settings = Settings()
    database = _database(settings)
    try:
        result = ArchiveLifecycleService(settings).execute(
            database,
            segment_id=uuid.UUID(segment_id),
            target_id=uuid.UUID(target_id),
        )
        return str(result.location_id)
    finally:
        database.close()



@huey.task(retries=2, retry_delay=30)
def delete_local_recording_location(
    location_id: str,
    pressure: bool = False,
) -> str:
    settings = Settings()
    database = _database(settings)
    try:
        result = LocalRetentionDeletionService.execute(
            database,
            location_id=uuid.UUID(location_id),
            pressure=pressure,
        )
        return result.reason
    finally:
        database.close()


def _run_retention_reconciliation(
    *,
    pressure: bool,
) -> dict[str, int]:
    settings = Settings()
    database = _database(settings)
    try:
        with database.session() as session:
            decisions = RetentionPlanner.plan(
                session,
                pressure=pressure,
                limit=500,
            )
            session.commit()

        archived = 0
        deleted = 0
        blocked = 0
        for decision in decisions:
            if decision.archive_target_id is not None:
                archive_recording_segment(
                    str(decision.segment_id),
                    str(decision.archive_target_id),
                )
                archived += 1
                continue

            if decision.eligible_for_delete:
                delete_local_recording_location(
                    str(decision.location_id),
                    pressure,
                )
                deleted += 1
                continue

            blocked += 1

        return {
            "archive_queued": archived,
            "delete_queued": deleted,
            "blocked": blocked,
        }
    finally:
        database.close()


@huey.task()
def reconcile_retention(
    pressure: bool = False,
) -> dict[str, int]:
    return _run_retention_reconciliation(
        pressure=pressure,
    )


@huey.periodic_task(crontab(minute="23"))
def periodic_retention_reconciliation() -> dict[str, int]:
    return _run_retention_reconciliation(
        pressure=False,
    )
