from __future__ import annotations

import fcntl
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
from app.core.errors import ApiError
from app.integrations.frigate import FrigateHttpAdapter
from app.modules.backups.execution import (
    BackupExecutionService,
    BackupRunService,
)
from app.modules.backups.models import BackupPolicy, BackupSet
from app.modules.backups.service import BackupPolicyService
from app.modules.cameras.media_runtime import CameraMediaRuntimeService
from app.modules.cameras.models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
)
from app.modules.events.frigate import FrigateEventIngestService
from app.modules.exports.execution import (
    ExportCleanupService,
    ExportExecutionService,
)
from app.modules.notifications.delivery import NotificationDeliveryService
from app.modules.recordings.models import RecordingPolicy
from app.modules.recordings.reconciliation import (
    RecordingCatalogReconciliationService,
)
from app.modules.recordings.playback_cache import PlaybackCacheService
from app.modules.recordings.policy import RecordingPolicyService
from app.modules.recordings.prebuffer import (
    PrebufferFragment,
    PrebufferPromotionService,
)
from app.modules.recordings.runtime import (
    RecorderModeTracker,
    RecordingRuntimeService,
)
from app.modules.recordings.triggers import RecordingTriggerService
from app.modules.storage.archive import ArchiveLifecycleService
from app.modules.storage.capacity import (
    LocalStorageCapacityService,
)
from app.modules.system.frigate import FrigateProviderSettingsService
from app.modules.system.health import write_worker_heartbeat
from app.modules.storage.retention import (
    LocalRetentionDeletionService,
    RetentionPlanner,
)
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)
from app.modules.storage.recording_resolver import RecordingStorageResolver

from .queue import huey


_RECORDER_MODE_TRACKER = RecorderModeTracker()


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
        RecordingStorageResolver.ensure_write_capacity(
            target
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


@huey.task(retries=3, retry_delay=15)
def reconcile_camera_runtime(
    camera_id: str,
    restart_streams: bool = False,
    force_reconfigure: bool = False,
) -> str:
    """Reconcile one Camera's ZLM recorder and stream runtime.

    Camera/RecordingPolicy rows are canonical. Disabling a Camera drives the
    recorder to off before closing its ZLM streams. Enabling a Camera restores
    the recorder required by its current policy; live-only streams remain
    demand-driven by the API.
    """

    settings = Settings()
    database = _database(settings)
    camera_uuid = uuid.UUID(camera_id)

    try:
        media_runtime = CameraMediaRuntimeService(settings)
        with database.session() as session:
            camera = session.get(Camera, camera_uuid)
            if camera is None:
                session.commit()
                return "missing"

            references = media_runtime.stream_references(
                camera=camera,
            )
            desired_streams = media_runtime.desired_streams(
                session,
                camera=camera,
            )
            desired_recorder = RecordingRuntimeService.desired(
                session,
                settings=settings,
                camera_id=camera_uuid,
                capacity_behavior="off",
            )
            enabled = camera.enabled

            record_streams = []
            if (
                desired_recorder is not None
                and desired_recorder.mode != "off"
            ):
                record_streams = [
                    item
                    for item in desired_streams
                    if item.profile_id
                    == desired_recorder.profile_id
                ]
                if not record_streams:
                    raise RuntimeError(
                        "camera RECORD stream is unavailable"
                    )
            session.commit()

        if restart_streams and enabled:
            media_runtime.replace_streams(
                desired_streams
            )
        elif record_streams:
            media_runtime.ensure_streams(
                record_streams
            )

        runtime_result = RecordingRuntimeService(
            settings,
            mode_tracker=_RECORDER_MODE_TRACKER,
        ).reconcile(
            desired_recorder,
            force_reconfigure=(
                restart_streams
                or force_reconfigure
            ),
        )

        if not enabled:
            media_runtime.stop_streams(references)

        return runtime_result.desired_mode
    finally:
        database.close()


@huey.task(retries=2, retry_delay=15)
def reconcile_manual_recording_boundary(
    camera_id: str,
) -> str:
    """Apply a MANUAL post-roll boundary without restarting baseline video."""

    settings = Settings()
    database = _database(settings)
    camera_uuid = uuid.UUID(camera_id)
    now = datetime.now(UTC)
    try:
        with database.session() as session:
            desired = RecordingRuntimeService.desired(
                session,
                settings=settings,
                camera_id=camera_uuid,
                at=now,
                capacity_behavior="off",
            )
            force_reconfigure = (
                desired is not None
                and desired.mode != "persistent"
            )
            session.commit()

        return reconcile_camera_runtime(
            camera_id,
            False,
            force_reconfigure,
        )
    finally:
        database.close()


@huey.periodic_task(
    crontab(minute="*/5")
)
def periodic_recording_capacity_guard(
) -> dict[str, int]:
    """Reconcile every enabled recording policy against current disk capacity.

    Critical local targets drive persistent recorders to off. Once capacity
    recovers, the same policy reconciliation restores the recorder without
    mutating the persisted RecordingPolicy.
    """
    settings = Settings()
    database = _database(settings)
    try:
        with database.session() as session:
            camera_ids = list(
                session.scalars(
                    select(
                        RecordingPolicy.camera_id
                    )
                    .where(
                        RecordingPolicy.enabled
                        .is_(True)
                    )
                    .order_by(
                        RecordingPolicy.camera_id
                    )
                )
            )
            targets = list(
                session.scalars(
                    select(StorageTarget)
                    .where(
                        StorageTarget.type
                        == "local",
                        StorageTarget.role
                        == "recording",
                        StorageTarget.enabled
                        .is_(True),
                    )
                )
            )
            session.commit()

        pressure_detected = False
        for target in targets:
            config = (
                target.config_json
                or {}
            )
            raw_path = config.get("path")
            if (
                not isinstance(
                    raw_path,
                    str,
                )
                or not raw_path
            ):
                continue
            try:
                capacity = (
                    LocalStorageCapacityService
                    .inspect(
                        root=Path(raw_path),
                        config=config,
                    )
                )
            except ApiError:
                continue
            if capacity.level in {
                "high",
                "critical",
            }:
                pressure_detected = True
                break

        queued = 0
        for camera_id in camera_ids:
            reconcile_camera_runtime(
                str(camera_id)
            )
            queued += 1

        if pressure_detected:
            reconcile_retention(False)

        return {
            "cameras_queued": queued,
            "pressure_reconcile_queued": (
                1
                if pressure_detected
                else 0
            ),
        }
    finally:
        database.close()


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
                capacity_behavior="off",
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

        RecordingRuntimeService(
            settings,
            mode_tracker=_RECORDER_MODE_TRACKER,
        ).reconcile(
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






def _run_recording_catalog_reconciliation(
    *,
    full: bool,
) -> dict[str, object]:
    settings = Settings()
    lock_path = (
        settings.cache_dir
        / "runtime"
        / "recording-reconciliation.lock"
    )
    lock_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with lock_path.open(
        "a+",
        encoding="utf-8",
    ) as lock_handle:
        try:
            fcntl.flock(
                lock_handle.fileno(),
                fcntl.LOCK_EX
                | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            return {
                "skipped_busy": True,
                "full": full,
            }

        database = _database(settings)
        try:
            result = (
                RecordingCatalogReconciliationService(
                    settings
                ).reconcile(
                    database,
                    full=full,
                )
            )
            return {
                "skipped_busy": False,
                "full": result.full,
                "scanned_files": (
                    result.scanned_files
                ),
                "changes": result.changes,
                "recovered": result.recovered,
                "recovered_partials": (
                    result.recovered_partials
                ),
                "relinked": result.relinked,
                "missing": result.missing,
                "ambiguous": (
                    result.ambiguous
                ),
                "errors": result.errors,
                "skipped_unsettled": (
                    result.skipped_unsettled
                ),
                "completed_at": (
                    result.completed_at
                    .isoformat()
                ),
            }
        finally:
            database.close()
            fcntl.flock(
                lock_handle.fileno(),
                fcntl.LOCK_UN,
            )


@huey.task(retries=2, retry_delay=60)
def reconcile_recording_catalog(
    full: bool = False,
) -> dict[str, object]:
    return _run_recording_catalog_reconciliation(
        full=full,
    )


@huey.periodic_task(
    crontab(minute="*/5")
)
def periodic_recording_catalog_reconciliation(
) -> dict[str, object]:
    return _run_recording_catalog_reconciliation(
        full=False,
    )


@huey.periodic_task(
    crontab(hour="3", minute="37")
)
def periodic_full_recording_catalog_reconciliation(
) -> dict[str, object]:
    return _run_recording_catalog_reconciliation(
        full=True,
    )


@huey.task(retries=3, retry_delay=30)
def restore_playback_segment(segment_id: str) -> str:
    settings = Settings()
    database = _database(settings)
    segment_uuid = uuid.UUID(segment_id)
    cache = PlaybackCacheService(settings)
    try:
        result = cache.execute(
            database,
            segment_id=segment_uuid,
        )
        return str(result.path)
    finally:
        cache.clear_restore_request(segment_id=segment_uuid)
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
            pressure_target_ids: set[
                uuid.UUID
            ] = set()
            if not pressure:
                targets = list(
                    session.scalars(
                        select(StorageTarget)
                        .where(
                            StorageTarget.type
                            == "local",
                            StorageTarget.role
                            == "recording",
                            StorageTarget.enabled
                            .is_(True),
                        )
                    )
                )
                for target in targets:
                    config = (
                        target.config_json
                        or {}
                    )
                    raw_path = config.get(
                        "path"
                    )
                    if (
                        not isinstance(
                            raw_path,
                            str,
                        )
                        or not raw_path
                    ):
                        continue
                    try:
                        capacity = (
                            LocalStorageCapacityService
                            .inspect(
                                root=Path(
                                    raw_path
                                ),
                                config=config,
                            )
                        )
                    except ApiError:
                        continue
                    if capacity.level in {
                        "high",
                        "critical",
                    }:
                        pressure_target_ids.add(
                            target.id
                        )

            batch = (
                RetentionPlanner
                .actionable_plan(
                    session,
                    pressure=pressure,
                    pressure_target_ids=(
                        pressure_target_ids
                    ),
                    page_size=500,
                    action_limit=500,
                )
            )
            session.commit()

        archived = 0
        deleted = 0
        for decision in batch.decisions:
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
                    (
                        pressure
                        or decision
                        .pressure_override
                    ),
                )
                deleted += 1
                continue

        return {
            "archive_queued": archived,
            "delete_queued": deleted,
            "blocked": batch.blocked,
            "scanned": batch.scanned,
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



def _frigate_backfill(
    *,
    lookback_seconds: int,
) -> dict[str, int]:
    if lookback_seconds < 60 or lookback_seconds > 86400:
        raise ValueError(
            "Frigate lookback must be between 60 and 86400 seconds"
        )

    settings = Settings()
    database = _database(settings)
    provider = FrigateProviderSettingsService(settings)

    try:
        with database.session() as session:
            config = provider.get(session)
            session.commit()

        if config is None or not config.enabled:
            return {
                "created": 0,
                "updated": 0,
                "ignored": 0,
            }

        now = datetime.now(UTC).timestamp()
        after = now - lookback_seconds
        created = 0
        updated = 0
        ignored = 0
        offset = 0
        batch_size = 200
        max_events = 5000

        with FrigateHttpAdapter(
            base_url=config.base_url,
            bearer_token=config.credentials.http_bearer_token,
            username=config.credentials.http_username,
            password=config.credentials.http_password,
            timeout_seconds=15.0,
        ) as adapter:
            while offset < max_events:
                items = adapter.events(
                    after=after,
                    before=now,
                    cameras=sorted(config.camera_map),
                    limit=batch_size,
                    offset=offset,
                )
                if not items:
                    break

                reconcile_cameras: set[uuid.UUID] = set()
                delivery_ids: set[uuid.UUID] = set()
                with database.session() as session:
                    for payload in items:
                        result = FrigateEventIngestService.http(
                            session,
                            config=config,
                            payload=payload,
                        )
                        if result.ignored:
                            ignored += 1
                        elif result.created:
                            created += 1
                        else:
                            updated += 1
                        if (
                            result.trigger_changed
                            and result.trigger_camera_id is not None
                        ):
                            reconcile_cameras.add(
                                result.trigger_camera_id
                            )
                        delivery_ids.update(
                            result.notification_delivery_ids
                        )
                    session.commit()

                for camera_id in reconcile_cameras:
                    reconcile_camera_prebuffer(
                        str(camera_id)
                    )
                for delivery_id in sorted(
                    delivery_ids,
                    key=str,
                ):
                    deliver_notification(
                        str(delivery_id)
                    )

                if len(items) < batch_size:
                    break
                offset += len(items)

        return {
            "created": created,
            "updated": updated,
            "ignored": ignored,
        }
    finally:
        database.close()


@huey.task(retries=3, retry_delay=30)
def backfill_frigate_events(
    lookback_seconds: int = 600,
) -> dict[str, int]:
    return _frigate_backfill(
        lookback_seconds=lookback_seconds,
    )


@huey.periodic_task(crontab(minute="*/5"))
def periodic_frigate_event_backfill() -> dict[str, int]:
    return _frigate_backfill(
        lookback_seconds=600,
    )



@huey.task(retries=3, retry_delay=30)
def deliver_notification(
    delivery_id: str,
) -> str:
    settings = Settings()
    database = _database(settings)
    try:
        result = NotificationDeliveryService(
            settings
        ).execute(
            database,
            delivery_id=uuid.UUID(delivery_id),
        )
        return result.state
    finally:
        database.close()



@huey.task(retries=2, retry_delay=30)
def render_export(export_id: str) -> str:
    settings = Settings()
    database = _database(settings)
    try:
        result = ExportExecutionService(
            settings
        ).execute(
            database,
            export_id=uuid.UUID(export_id),
        )
        return result.state
    finally:
        database.close()


@huey.periodic_task(crontab(minute="17"))
def expire_exports() -> int:
    settings = Settings()
    database = _database(settings)
    try:
        return ExportCleanupService.expire(
            database
        )
    finally:
        database.close()



@huey.task(retries=2, retry_delay=60)
def run_backup_set(backup_set_id: str) -> str:
    settings = Settings()
    database = _database(settings)
    try:
        state = BackupExecutionService(
            settings
        ).execute(
            database,
            backup_set_id=uuid.UUID(backup_set_id),
        )
        if state == "FAILED":
            raise RuntimeError("backup execution failed")
        return state
    finally:
        database.close()


@huey.task(retries=2, retry_delay=60)
def verify_backup_set(backup_set_id: str) -> str:
    settings = Settings()
    database = _database(settings)
    try:
        state = BackupExecutionService(
            settings
        ).verify(
            database,
            backup_set_id=uuid.UUID(backup_set_id),
        )
        if state == "FAILED":
            raise RuntimeError("backup verification failed")
        return state
    finally:
        database.close()


@huey.periodic_task(crontab(minute="*"))
def schedule_backups() -> dict[str, int]:
    settings = Settings()
    database = _database(settings)
    now = datetime.now(UTC).replace(
        second=0,
        microsecond=0,
    )
    queued = 0
    checks = 0

    try:
        with database.session() as session:
            policies = list(
                session.scalars(
                    select(BackupPolicy).where(
                        BackupPolicy.enabled.is_(True)
                    )
                )
            )

            run_ids: list[uuid.UUID] = []
            verify_ids: list[uuid.UUID] = []
            for policy in policies:
                if BackupPolicyService.schedule_matches(
                    policy,
                    at=now,
                ):
                    backup_set, created = BackupRunService.reserve(
                        session,
                        policy=policy,
                        settings=settings,
                        database=database,
                        reason="scheduled",
                        schedule_slot=BackupPolicyService.schedule_slot(
                            at=now
                        ),
                    )
                    if created:
                        run_ids.append(backup_set.id)

                if BackupPolicyService.schedule_value_matches(
                    policy.repository_check_schedule_json or {},
                    at=now,
                ):
                    latest = session.scalar(
                        select(BackupSet)
                        .where(
                            BackupSet.backup_policy_id
                            == policy.id,
                            BackupSet.state == "COMPLETED",
                            BackupSet.restic_snapshot_id.is_not(
                                None
                            ),
                        )
                        .order_by(
                            BackupSet.started_at.desc(),
                            BackupSet.id.desc(),
                        )
                        .limit(1)
                    )
                    if latest is not None:
                        minute_start = now
                        if (
                            latest.last_verified_at is None
                            or latest.last_verified_at < minute_start
                        ):
                            latest.verification_state = "PENDING"
                            verify_ids.append(latest.id)

            session.commit()

        for backup_id in run_ids:
            run_backup_set(str(backup_id))
            queued += 1
        for backup_id in verify_ids:
            verify_backup_set(str(backup_id))
            checks += 1

        return {
            "backups_queued": queued,
            "checks_queued": checks,
        }
    finally:
        database.close()



@huey.periodic_task(crontab(minute="*"))
def worker_heartbeat() -> str:
    settings = Settings()
    return str(
        write_worker_heartbeat(settings)
    )
