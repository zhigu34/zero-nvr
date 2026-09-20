from __future__ import annotations

import os
import shutil
import threading
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.recordings.models import RecordingSegment
from app.modules.storage.models import RecordingLocation




def _mount_filesystem_type(path: Path) -> str | None:
    """Return the Linux filesystem type for the longest matching mount."""

    try:
        lines = Path("/proc/self/mountinfo").read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError:
        return None

    resolved = path.resolve()
    best: tuple[int, str] | None = None

    for line in lines:
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        left_fields = left.split()
        right_fields = right.split()
        if len(left_fields) < 5 or not right_fields:
            continue

        mount_text = (
            left_fields[4]
            .replace("\\040", " ")
            .replace("\\011", "\t")
            .replace("\\134", "\\")
        )
        mount = Path(mount_text)
        try:
            resolved.relative_to(mount)
        except ValueError:
            continue

        score = len(mount.parts)
        fs_type = right_fields[0]
        if best is None or score > best[0]:
            best = (score, fs_type)

    return best[1] if best is not None else None


def validate_prebuffer_root(settings: Settings) -> Path:
    root = settings.prebuffer_dir.resolve()
    if not root.is_dir():
        raise ApiError(
            status_code=409,
            code="prebuffer_unavailable",
            message="EVENT_ONLY recording requires the configured prebuffer mount.",
        )
    if not os.access(root, os.W_OK | os.X_OK):
        raise ApiError(
            status_code=409,
            code="prebuffer_unwritable",
            message="The configured prebuffer mount is not writable.",
        )

    if settings.prebuffer_require_tmpfs:
        fs_type = _mount_filesystem_type(root)
        if fs_type != "tmpfs":
            raise ApiError(
                status_code=409,
                code="prebuffer_not_tmpfs",
                message="EVENT_ONLY prebuffer must be backed by a bounded tmpfs mount.",
                details={"filesystem_type": fs_type},
            )
    return root


@dataclass(frozen=True, slots=True)
class PrebufferFragment:
    camera_id: uuid.UUID
    profile_id: uuid.UUID
    continuity_id: uuid.UUID | None
    vhost: str
    app: str
    stream: str
    file_path: Path
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PromotionReceipt:
    fragment: PrebufferFragment
    storage_target_id: uuid.UUID
    object_path: str
    destination: Path
    size_bytes: int


class PrebufferFragmentTracker:
    """Bounded in-memory finalized prebuffer facts.

    Durable RecordingTrigger rows plus the tmpfs filesystem are the restart
    recovery source. This tracker is only the normal hook fast path.
    """

    def __init__(self, *, max_fragments_per_stream: int = 256) -> None:
        if max_fragments_per_stream < 8:
            raise ValueError("prebuffer tracker bound is too small")
        self._max = max_fragments_per_stream
        self._lock = threading.Lock()
        self._items: dict[
            tuple[str, str, str],
            deque[PrebufferFragment],
        ] = defaultdict(lambda: deque(maxlen=self._max))

    @staticmethod
    def _identity(
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> tuple[str, str, str]:
        return (vhost, app, stream)

    def observe(
        self,
        *,
        camera_id: uuid.UUID,
        profile_id: uuid.UUID,
        continuity_id: uuid.UUID | None,
        vhost: str,
        app: str,
        stream: str,
        file_path: str,
        start_time_epoch: float,
        duration_seconds: float,
        size_bytes: int,
    ) -> PrebufferFragment:
        started_at = datetime.fromtimestamp(start_time_epoch, tz=UTC)
        duration_ms = max(
            1,
            int(round(duration_seconds * 1000)),
        )
        ended_at = started_at + timedelta(milliseconds=duration_ms)

        fragment = PrebufferFragment(
            camera_id=camera_id,
            profile_id=profile_id,
            continuity_id=continuity_id,
            vhost=vhost,
            app=app,
            stream=stream,
            file_path=Path(file_path),
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            size_bytes=size_bytes,
        )

        identity = self._identity(
            vhost=vhost,
            app=app,
            stream=stream,
        )
        with self._lock:
            items = self._items[identity]

            for existing in items:
                if existing.file_path == fragment.file_path:
                    return existing

            if items:
                previous = items[-1]
                if (
                    previous.continuity_id is not None
                    and previous.continuity_id == continuity_id
                    and started_at > previous.started_at
                ):
                    normalized_start = started_at - timedelta(
                        milliseconds=previous.duration_ms
                    )
                    if normalized_start < started_at:
                        items[-1] = replace(
                            previous,
                            started_at=normalized_start,
                            ended_at=started_at,
                        )

            items.append(fragment)
            return fragment

    def fragments_for_camera(
        self,
        camera_id: uuid.UUID,
    ) -> list[PrebufferFragment]:
        with self._lock:
            return sorted(
                [
                    item
                    for queue in self._items.values()
                    for item in queue
                    if item.camera_id == camera_id
                ],
                key=lambda item: (
                    item.started_at,
                    str(item.file_path),
                ),
            )

    def overlapping(
        self,
        *,
        camera_id: uuid.UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> list[PrebufferFragment]:
        return [
            item
            for item in self.fragments_for_camera(camera_id)
            if item.started_at < end_at
            and item.ended_at > start_at
        ]

    def remove_path(self, file_path: Path) -> None:
        with self._lock:
            for identity, queue in list(self._items.items()):
                kept = [
                    item
                    for item in queue
                    if item.file_path != file_path
                ]
                if len(kept) != len(queue):
                    self._items[identity] = deque(
                        kept,
                        maxlen=self._max,
                    )
                if not self._items[identity]:
                    self._items.pop(identity, None)


class PrebufferPromotionService:
    @staticmethod
    def prepare(
        *,
        fragment: PrebufferFragment,
        prebuffer_root: Path,
        storage_target_id: uuid.UUID,
        target_root: Path,
    ) -> PromotionReceipt:
        source = fragment.file_path.resolve()
        root = prebuffer_root.resolve()
        try:
            relative = source.relative_to(root)
        except ValueError as exc:
            raise ApiError(
                status_code=409,
                code="prebuffer_fragment_outside_root",
                message="Prebuffer fragment is outside the configured prebuffer root.",
            ) from exc

        resolved_target_root = target_root.resolve()
        destination = (
            resolved_target_root
            / "event"
            / relative
        ).resolve()
        try:
            destination.relative_to(resolved_target_root)
        except ValueError as exc:
            raise ApiError(
                status_code=409,
                code="prebuffer_promotion_path_invalid",
                message="Prebuffer promotion destination is invalid.",
            ) from exc

        if destination.is_file():
            published_size = destination.stat().st_size
            if published_size != fragment.size_bytes:
                raise ApiError(
                    status_code=409,
                    code="prebuffer_promotion_size_mismatch",
                    message="Existing promoted fragment has an unexpected size.",
                )
            return PromotionReceipt(
                fragment=fragment,
                storage_target_id=storage_target_id,
                object_path=destination.relative_to(
                    resolved_target_root
                ).as_posix(),
                destination=destination,
                size_bytes=published_size,
            )

        if not source.is_file():
            raise ApiError(
                status_code=409,
                code="prebuffer_fragment_missing",
                message="Prebuffer fragment is no longer available.",
            )

        partial = destination.with_name(
            destination.name + ".partial"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(source, partial)
        copied_size = partial.stat().st_size
        if copied_size != fragment.size_bytes:
            partial.unlink(missing_ok=True)
            raise ApiError(
                status_code=409,
                code="prebuffer_promotion_size_mismatch",
                message="Promoted fragment size verification failed.",
            )

        with partial.open("rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(partial, destination)

        return PromotionReceipt(
            fragment=fragment,
            storage_target_id=storage_target_id,
            object_path=destination.relative_to(
                resolved_target_root
            ).as_posix(),
            destination=destination,
            size_bytes=copied_size,
        )

    @staticmethod
    def commit(
        session: Session,
        *,
        receipt: PromotionReceipt,
    ) -> RecordingSegment:
        existing_location = session.scalar(
            select(RecordingLocation).where(
                RecordingLocation.storage_target_id
                == receipt.storage_target_id,
                RecordingLocation.object_path
                == receipt.object_path,
            )
        )
        if existing_location is not None:
            existing = session.get(
                RecordingSegment,
                existing_location.recording_segment_id,
            )
            if existing is None:
                raise ApiError(
                    status_code=409,
                    code="recording_catalog_inconsistent",
                    message="Promoted location references a missing recording segment.",
                )
            if existing_location.size_bytes != receipt.size_bytes:
                raise ApiError(
                    status_code=409,
                    code="recording_location_conflict",
                    message="Promoted recording path already exists with different media facts.",
                )
            return existing

        fragment = receipt.fragment
        segment = RecordingSegment(
            camera_id=fragment.camera_id,
            stream_profile_id=fragment.profile_id,
            started_at=fragment.started_at,
            ended_at=fragment.ended_at,
            duration_ms=fragment.duration_ms,
            timing_status="PROVISIONAL",
            timing_source="HOOK_RAW",
            recording_reasons_json=["event"],
            size_bytes=receipt.size_bytes,
            codec=None,
            container="fmp4",
            source_media_server_id="default",
            source_app=fragment.app,
            source_stream=fragment.stream,
            integrity_status="UNKNOWN",
            completion_reason="PROMOTED_EVENT",
        )
        session.add(segment)
        session.flush()

        segment.locations.append(
            RecordingLocation(
                recording_segment_id=segment.id,
                storage_target_id=receipt.storage_target_id,
                object_path=receipt.object_path,
                state="AVAILABLE",
                size_bytes=receipt.size_bytes,
            )
        )
        session.flush()
        return segment
