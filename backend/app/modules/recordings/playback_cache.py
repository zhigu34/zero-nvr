from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.integrations.rclone import RcloneAdapter, RcloneIntegrationError
from app.modules.storage.models import RecordingLocation, StorageTarget
from app.modules.storage.service import StorageTargetService
from app.modules.system.settings import (
    RuntimeTuningSettings,
    RuntimeTuningSettingsService,
)

from .models import RecordingSegment


class PlaybackCacheError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PlaybackRestorePlan:
    segment_id: uuid.UUID
    source_path: str
    destination: Path
    expected_size: int
    rclone_config: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class PlaybackRestoreResult:
    path: Path
    restored: bool
    already_cached: bool
    in_progress: bool = False


class PlaybackCacheService:
    """Bounded, ephemeral cache for remote-only playback media."""

    def __init__(
        self,
        settings: Settings,
        *,
        adapter_factory: Callable[..., RcloneAdapter] = RcloneAdapter,
        target_service_factory: Callable[[Settings], Any] = StorageTargetService,
        tuning: RuntimeTuningSettings | None = None,
    ) -> None:
        self.settings = settings
        self._adapter_factory = adapter_factory
        self._target_service_factory = target_service_factory
        self._runtime_tuning = tuning

    def _tuning(
        self,
        database: Database | None = None,
    ) -> RuntimeTuningSettings:
        if self._runtime_tuning is not None:
            return self._runtime_tuning
        if database is None:
            return RuntimeTuningSettingsService.defaults(
                self.settings
            )
        with database.session() as session:
            return RuntimeTuningSettingsService.get(
                session,
                settings=self.settings,
            )

    @property
    def root(self) -> Path:
        return self.settings.cache_dir / "playback"

    def path_for(self, segment_id: uuid.UUID) -> Path:
        return self.root / f"{segment_id.hex}.mp4"

    def request_path(self, segment_id: uuid.UUID) -> Path:
        return self.root / f"{segment_id.hex}.request"

    def reserve_restore(self, *, segment_id: uuid.UUID) -> bool:
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.request_path(segment_id)

        def create() -> bool:
            try:
                fd = os.open(
                    marker,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                return False
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            return True

        if create():
            return True

        try:
            age = time.time() - marker.stat().st_mtime
        except OSError:
            age = 0

        if (
            age
            <= self._tuning()
            .playback_restore_lock_ttl_seconds
        ):
            return False

        try:
            marker.unlink(missing_ok=True)
        except OSError:
            return False
        return create()

    def clear_restore_request(self, *, segment_id: uuid.UUID) -> None:
        try:
            self.request_path(segment_id).unlink(missing_ok=True)
        except OSError:
            pass

    def cached_file(
        self,
        *,
        segment_id: uuid.UUID,
        expected_size: int,
    ) -> Path | None:
        path = self.path_for(segment_id)
        try:
            if not path.is_file():
                return None
            if path.stat().st_size != expected_size:
                path.unlink(missing_ok=True)
                return None
            os.utime(path, None)
            return path
        except OSError:
            return None

    def _prune(
        self,
        database: Database,
        *,
        protected: set[Path] | None = None,
    ) -> None:
        protected = {
            item.resolve(strict=False)
            for item in (protected or set())
        }
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        now = time.time()
        tuning = self._tuning(database)
        ttl = tuning.playback_cache_ttl_seconds

        files: list[tuple[float, int, Path]] = []
        for path in root.glob("*.mp4"):
            try:
                resolved = path.resolve(strict=False)
                stat = path.stat()
            except OSError:
                continue

            if resolved not in protected and now - stat.st_mtime > ttl:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue

            files.append((stat.st_mtime, stat.st_size, path))

        total = sum(size for _, size, _ in files)
        if total <= tuning.playback_cache_max_bytes:
            return

        for _mtime, size, path in sorted(files):
            if total <= tuning.playback_cache_max_bytes:
                break
            if path.resolve(strict=False) in protected:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            total -= size

    def prepare(
        self,
        database: Database,
        *,
        segment_id: uuid.UUID,
    ) -> PlaybackRestorePlan | PlaybackRestoreResult:
        with database.session() as session:
            segment = session.get(RecordingSegment, segment_id)
            if segment is None:
                raise PlaybackCacheError(
                    "playback_segment_missing",
                    "Recording segment is unavailable.",
                )

            cached = self.cached_file(
                segment_id=segment.id,
                expected_size=segment.size_bytes,
            )
            if cached is not None:
                session.commit()
                return PlaybackRestoreResult(
                    path=cached,
                    restored=False,
                    already_cached=True,
                )

            row = session.execute(
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
                    StorageTarget.type == "rclone",
                    StorageTarget.role == "archive",
                    StorageTarget.enabled.is_(True),
                )
                .order_by(
                    RecordingLocation.created_at,
                    RecordingLocation.id,
                )
                .limit(1)
            ).first()
            if row is None:
                raise PlaybackCacheError(
                    "playback_remote_source_unavailable",
                    "No available remote recording copy exists.",
                )

            location, target = row
            resolved = self._target_service_factory(
                self.settings
            ).resolve_rclone(
                session,
                target=target,
            )
            plan = PlaybackRestorePlan(
                segment_id=segment.id,
                source_path=resolved.object_path(location.object_path),
                destination=self.path_for(segment.id),
                expected_size=location.size_bytes,
                rclone_config=resolved.config_text,
            )
            session.commit()
            return plan

    def _acquire_lock(
        self,
        database: Database,
        destination: Path,
    ) -> Path | None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        lock = destination.with_name(destination.name + ".lock")

        def create() -> bool:
            try:
                fd = os.open(
                    lock,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                return False
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            return True

        if create():
            return lock

        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            age = 0

        if (
            age
            <= self._tuning(database)
            .playback_restore_lock_ttl_seconds
        ):
            return None

        try:
            lock.unlink(missing_ok=True)
        except OSError:
            return None
        return lock if create() else None

    def execute(
        self,
        database: Database,
        *,
        segment_id: uuid.UUID,
    ) -> PlaybackRestoreResult:
        prepared = self.prepare(
            database,
            segment_id=segment_id,
        )
        if isinstance(prepared, PlaybackRestoreResult):
            return prepared

        plan = prepared
        lock = self._acquire_lock(
            database,
            plan.destination,
        )
        if lock is None:
            return PlaybackRestoreResult(
                path=plan.destination,
                restored=False,
                already_cached=False,
                in_progress=True,
            )

        try:
            cached = self.cached_file(
                segment_id=plan.segment_id,
                expected_size=plan.expected_size,
            )
            if cached is not None:
                return PlaybackRestoreResult(
                    path=cached,
                    restored=False,
                    already_cached=True,
                )

            self._prune(
                database,
                protected={plan.destination},
            )
            adapter = self._adapter_factory(
                config_text=plan.rclone_config,
                binary=self.settings.rclone_binary,
                timeout_seconds=self.settings.rclone_timeout_seconds,
            )
            try:
                adapter.copy_to_local(
                    source=plan.source_path,
                    destination=plan.destination,
                    expected_size=plan.expected_size,
                )
            except RcloneIntegrationError as exc:
                raise PlaybackCacheError(
                    exc.code,
                    str(exc),
                ) from exc

            os.utime(plan.destination, None)
            self._prune(
                database,
                protected={plan.destination},
            )
            return PlaybackRestoreResult(
                path=plan.destination,
                restored=True,
                already_cached=False,
            )
        finally:
            lock.unlink(missing_ok=True)
