from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.errors import ApiError
from app.integrations.zlm import ZlmAdapter
from app.modules.storage.models import RecordingLocation

from .models import RecordingSegment
from .playback_cache import PlaybackCacheService
from .timeline import PlaybackTimelineService


@dataclass(frozen=True, slots=True)
class PlayablePlan:
    segment_id: uuid.UUID
    segment_start_at: datetime
    offset_ms: int
    file_path: Path
    codec: str | None


@dataclass(frozen=True, slots=True)
class PendingPlan:
    segment_id: uuid.UUID
    reason: Literal["remote_restore_required"]


@dataclass(frozen=True, slots=True)
class GapPlan:
    reason: str
    previous_at: datetime | None
    next_at: datetime | None


PlaybackPlan = PlayablePlan | PendingPlan | GapPlan


class PlaybackResolverService:
    vod_app = "zero-nvr-vod"
    descriptor_ttl_seconds = 300

    @staticmethod
    def filesystem_path(
        location: RecordingLocation,
    ) -> Path | None:
        target = location.storage_target
        config = target.config_json or {}

        if target.type == "local":
            raw_root = config.get("path")
        elif target.type == "rclone":
            raw_root = config.get("mount_path")
        else:
            return None

        if not isinstance(raw_root, str) or not raw_root.strip():
            return None

        root = Path(raw_root).expanduser()
        if not root.is_absolute():
            return None

        resolved_root = root.resolve(strict=False)
        candidate = (
            resolved_root / location.object_path
        ).resolve(strict=False)
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            return None
        return candidate

    @staticmethod
    def _offset_ms(*, at: datetime, segment: RecordingSegment) -> int:
        return max(
            0,
            int(
                round(
                    (at - segment.started_at).total_seconds()
                    * 1000
                )
            ),
        )

    @staticmethod
    def _neighbors(
        session: Session,
        *,
        camera_id: uuid.UUID,
        at: datetime,
    ) -> tuple[datetime | None, datetime | None]:
        previous = session.scalar(
            select(RecordingSegment.ended_at)
            .where(
                RecordingSegment.camera_id == camera_id,
                RecordingSegment.ended_at <= at,
            )
            .order_by(RecordingSegment.ended_at.desc())
            .limit(1)
        )
        next_at = session.scalar(
            select(RecordingSegment.started_at)
            .where(
                RecordingSegment.camera_id == camera_id,
                RecordingSegment.started_at > at,
            )
            .order_by(RecordingSegment.started_at)
            .limit(1)
        )
        return previous, next_at

    @classmethod
    def plan(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        at: datetime,
        settings: Settings | None = None,
    ) -> PlaybackPlan:
        segments = list(
            session.scalars(
                select(RecordingSegment)
                .options(
                    selectinload(RecordingSegment.locations).joinedload(
                        RecordingLocation.storage_target
                    )
                )
                .where(
                    RecordingSegment.camera_id == camera_id,
                    RecordingSegment.started_at <= at,
                    RecordingSegment.ended_at > at,
                )
                .order_by(
                    RecordingSegment.started_at.desc(),
                    RecordingSegment.id.desc(),
                )
            )
        )

        for segment in segments:
            if settings is not None:
                cached = PlaybackCacheService(settings).cached_file(
                    segment_id=segment.id,
                    expected_size=segment.size_bytes,
                )
                if cached is not None:
                    return PlayablePlan(
                        segment_id=segment.id,
                        segment_start_at=segment.started_at,
                        offset_ms=cls._offset_ms(
                            at=at,
                            segment=segment,
                        ),
                        file_path=cached,
                        codec=segment.codec,
                    )

            available = [
                item
                for item in segment.locations
                if item.state == "AVAILABLE"
            ]
            available.sort(
                key=lambda item: (
                    0
                    if item.storage_target.type == "local"
                    else 1,
                    str(item.id),
                )
            )

            remote_without_mount = False
            for location in available:
                path = cls.filesystem_path(location)
                if path is not None:
                    offset_ms = cls._offset_ms(
                        at=at,
                        segment=segment,
                    )
                    return PlayablePlan(
                        segment_id=segment.id,
                        segment_start_at=segment.started_at,
                        offset_ms=offset_ms,
                        file_path=path,
                        codec=segment.codec,
                    )

                if location.storage_target.type == "rclone":
                    remote_without_mount = True

            if remote_without_mount:
                return PendingPlan(
                    segment_id=segment.id,
                    reason="remote_restore_required",
                )

        previous_at, next_at = cls._neighbors(
            session,
            camera_id=camera_id,
            at=at,
        )

        if segments:
            reason = "missing_media"
        else:
            # Reuse the same product gap semantics as Timeline rather than
            # inventing a second gap classifier.
            reason = PlaybackTimelineService._empty_reason(
                session,
                camera_id=camera_id,
                start_at=at,
                end_at=at + timedelta(milliseconds=1),
            )

        return GapPlan(
            reason=reason,
            previous_at=previous_at,
            next_at=next_at,
        )

    @classmethod
    def activate(
        cls,
        settings: Settings,
        plan: PlayablePlan,
    ) -> tuple[str, datetime]:
        if not plan.file_path.is_file():
            raise ApiError(
                status_code=409,
                code="recording_media_missing",
                message="The selected recording file is missing.",
                details={"segment_id": str(plan.segment_id)},
            )

        stream = (
            f"segment-{plan.segment_id.hex}-"
            f"{uuid.uuid4().hex}"
        )
        with ZlmAdapter(settings) as zlm:
            if not zlm.load_mp4_file(
                app=cls.vod_app,
                stream=stream,
                file_path=str(plan.file_path),
                seek_ms=plan.offset_ms,
                speed=1.0,
            ):
                raise ApiError(
                    status_code=503,
                    code="playback_media_load_failed",
                    message="ZLMediaKit could not load the recording.",
                )

        base = settings.zlm_public_base_url.rstrip("/")
        url = f"{base}/{cls.vod_app}/{stream}.live.mp4"
        expires_at = datetime.now(UTC) + timedelta(
            seconds=cls.descriptor_ttl_seconds
        )
        return url, expires_at
