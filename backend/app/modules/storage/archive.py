from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.core.db.types import utc_now
from app.integrations.rclone import RcloneAdapter, RcloneIntegrationError
from app.modules.recordings.models import RecordingSegment

from .models import RecordingLocation, StorageTarget
from .service import StorageTargetService


class ArchiveLifecycleError(RuntimeError):
    """Sanitized background archive failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ArchivePlan:
    segment_id: uuid.UUID
    remote_location_id: uuid.UUID
    remote_target_id: uuid.UUID
    source_location_id: uuid.UUID
    source_path: Path
    object_path: str
    remote_path: str
    expected_size: int
    rclone_config: str = field(repr=False)
    verify_existing: bool = False


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    location_id: uuid.UUID
    transferred: bool
    already_available: bool


class ArchiveLifecycleService:
    """Copy immutable recording objects to an rclone archive target.

    Database state preparation/finalization is deliberately separated from the
    remote transfer. No SQLite transaction remains open while rclone runs.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        adapter_factory: Callable[..., RcloneAdapter] = RcloneAdapter,
    ) -> None:
        self.settings = settings
        self._adapter_factory = adapter_factory

    @staticmethod
    def _safe_local_path(
        *,
        target: StorageTarget,
        object_path: str,
    ) -> Path:
        config = target.config_json or {}
        raw_root = config.get("path")
        if not isinstance(raw_root, str) or not raw_root:
            raise ArchiveLifecycleError(
                "archive_source_target_invalid",
                "Local recording storage target is invalid.",
            )

        root = Path(raw_root).expanduser().resolve(strict=False)
        candidate = (root / object_path).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ArchiveLifecycleError(
                "archive_source_path_invalid",
                "Recording source path is invalid.",
            ) from exc
        return candidate

    def prepare(
        self,
        database: Database,
        *,
        segment_id: uuid.UUID,
        target_id: uuid.UUID,
    ) -> ArchivePlan | ArchiveResult:
        with database.session() as session:
            segment = session.get(RecordingSegment, segment_id)
            if segment is None:
                raise ArchiveLifecycleError(
                    "archive_segment_missing",
                    "Recording segment is unavailable.",
                )

            remote_target = session.get(StorageTarget, target_id)
            if (
                remote_target is None
                or remote_target.type != "rclone"
                or remote_target.role != "archive"
                or not remote_target.enabled
            ):
                raise ArchiveLifecycleError(
                    "archive_target_unavailable",
                    "Archive storage target is unavailable.",
                )

            source_row = session.execute(
                select(RecordingLocation, StorageTarget)
                .join(
                    StorageTarget,
                    StorageTarget.id
                    == RecordingLocation.storage_target_id,
                )
                .where(
                    RecordingLocation.recording_segment_id
                    == segment.id,
                    RecordingLocation.state == "AVAILABLE",
                    StorageTarget.type == "local",
                    StorageTarget.role == "recording",
                    StorageTarget.enabled.is_(True),
                )
                .order_by(
                    RecordingLocation.created_at,
                    RecordingLocation.id,
                )
                .limit(1)
            ).first()
            if source_row is None:
                raise ArchiveLifecycleError(
                    "archive_source_unavailable",
                    "No available local recording copy exists.",
                )

            source_location, source_target = source_row
            object_path = source_location.object_path
            expected_size = source_location.size_bytes

            existing = session.scalar(
                select(RecordingLocation).where(
                    RecordingLocation.storage_target_id
                    == remote_target.id,
                    RecordingLocation.object_path == object_path,
                )
            )
            if (
                existing is not None
                and existing.recording_segment_id
                != segment.id
            ):
                raise ArchiveLifecycleError(
                    "archive_location_conflict",
                    "Archive object path is already owned by another recording segment.",
                )

            verify_existing = False
            if (
                existing is not None
                and existing.state == "AVAILABLE"
            ):
                if existing.size_bytes != expected_size:
                    raise ArchiveLifecycleError(
                        "archive_location_conflict",
                        "Archive location exists with different media facts.",
                    )
                if existing.verified_at is not None:
                    session.commit()
                    return ArchiveResult(
                        location_id=existing.id,
                        transferred=False,
                        already_available=True,
                    )
                verify_existing = True

            resolved = StorageTargetService(
                self.settings
            ).resolve_rclone(
                session,
                target=remote_target,
            )
            source_path = self._safe_local_path(
                target=source_target,
                object_path=object_path,
            )
            remote_path = resolved.object_path(object_path)

            now = utc_now()
            if existing is None:
                existing = RecordingLocation(
                    recording_segment_id=segment.id,
                    storage_target_id=remote_target.id,
                    object_path=object_path,
                    state="ARCHIVING",
                    size_bytes=expected_size,
                    last_attempt_at=now,
                )
                session.add(existing)
                session.flush()
            elif verify_existing:
                existing.last_attempt_at = now
                existing.last_error = None
                session.flush()
            else:
                existing.state = "ARCHIVING"
                existing.size_bytes = expected_size
                existing.last_attempt_at = now
                existing.last_error = None
                existing.deleted_at = None
                session.flush()

            plan = ArchivePlan(
                segment_id=segment.id,
                remote_location_id=existing.id,
                remote_target_id=remote_target.id,
                source_location_id=source_location.id,
                source_path=source_path,
                object_path=object_path,
                remote_path=remote_path,
                expected_size=expected_size,
                verify_existing=verify_existing,
                rclone_config=resolved.config_text,
            )
            session.commit()
            return plan

    @staticmethod
    def _mark_source_missing(
        database: Database,
        *,
        source_location_id: uuid.UUID,
    ) -> None:
        with database.session() as session:
            source = session.get(
                RecordingLocation,
                source_location_id,
            )
            if source is not None and source.state == "AVAILABLE":
                source.state = "MISSING"
                source.last_error = "archive_source_missing"
                source.last_attempt_at = utc_now()
                session.commit()

    @staticmethod
    def _mark_failed(
        database: Database,
        *,
        location_id: uuid.UUID,
        error_code: str,
    ) -> None:
        with database.session() as session:
            location = session.get(
                RecordingLocation,
                location_id,
            )
            if location is not None:
                location.state = "FAILED"
                location.last_attempt_at = utc_now()
                location.last_error = error_code
                session.commit()

    @staticmethod
    def _mark_available(
        database: Database,
        *,
        location_id: uuid.UUID,
        expected_size: int,
    ) -> None:
        with database.session() as session:
            location = session.get(
                RecordingLocation,
                location_id,
            )
            if location is None:
                raise ArchiveLifecycleError(
                    "archive_location_missing",
                    "Archive location disappeared before verification completed.",
                )
            location.state = "AVAILABLE"
            location.size_bytes = expected_size
            location.verified_at = utc_now()
            location.last_attempt_at = utc_now()
            location.last_error = None
            location.deleted_at = None
            session.commit()

    def execute(
        self,
        database: Database,
        *,
        segment_id: uuid.UUID,
        target_id: uuid.UUID,
    ) -> ArchiveResult:
        prepared = self.prepare(
            database,
            segment_id=segment_id,
            target_id=target_id,
        )
        if isinstance(prepared, ArchiveResult):
            return prepared

        plan = prepared

        if plan.verify_existing:
            try:
                adapter = self._adapter_factory(
                    config_text=plan.rclone_config,
                    binary=self.settings.rclone_binary,
                    timeout_seconds=(
                        self.settings
                        .rclone_timeout_seconds
                    ),
                )
                remote_stat = adapter.stat(
                    plan.remote_path
                )
                if (
                    remote_stat.size_bytes
                    != plan.expected_size
                ):
                    raise ArchiveLifecycleError(
                        "rclone_size_mismatch",
                        "Archived object size verification failed.",
                    )
            except RcloneIntegrationError as exc:
                self._mark_failed(
                    database,
                    location_id=(
                        plan.remote_location_id
                    ),
                    error_code=exc.code,
                )
                raise ArchiveLifecycleError(
                    exc.code,
                    str(exc),
                ) from exc
            except ArchiveLifecycleError as exc:
                self._mark_failed(
                    database,
                    location_id=(
                        plan.remote_location_id
                    ),
                    error_code=exc.code,
                )
                raise

            self._mark_available(
                database,
                location_id=(
                    plan.remote_location_id
                ),
                expected_size=plan.expected_size,
            )
            return ArchiveResult(
                location_id=(
                    plan.remote_location_id
                ),
                transferred=False,
                already_available=True,
            )

        try:
            if not plan.source_path.is_file():
                self._mark_source_missing(
                    database,
                    source_location_id=plan.source_location_id,
                )
                raise ArchiveLifecycleError(
                    "archive_source_missing",
                    "Recording source file is unavailable.",
                )

            actual_size = plan.source_path.stat().st_size
            if actual_size != plan.expected_size:
                raise ArchiveLifecycleError(
                    "archive_source_size_mismatch",
                    "Recording source size no longer matches catalog facts.",
                )

            adapter = self._adapter_factory(
                config_text=plan.rclone_config,
                binary=self.settings.rclone_binary,
                timeout_seconds=self.settings.rclone_timeout_seconds,
            )
            adapter.copy_to_remote(
                source=plan.source_path,
                destination=plan.remote_path,
                expected_size=plan.expected_size,
            )
        except RcloneIntegrationError as exc:
            self._mark_failed(
                database,
                location_id=plan.remote_location_id,
                error_code=exc.code,
            )
            raise ArchiveLifecycleError(
                exc.code,
                str(exc),
            ) from exc
        except ArchiveLifecycleError as exc:
            self._mark_failed(
                database,
                location_id=plan.remote_location_id,
                error_code=exc.code,
            )
            raise

        self._mark_available(
            database,
            location_id=plan.remote_location_id,
            expected_size=plan.expected_size,
        )
        return ArchiveResult(
            location_id=plan.remote_location_id,
            transferred=True,
            already_available=False,
        )
