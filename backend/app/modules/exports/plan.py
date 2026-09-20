from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiError
from app.modules.recordings.models import RecordingSegment
from app.modules.recordings.playback import PlaybackResolverService
from app.modules.storage.models import RecordingLocation


@dataclass(frozen=True, slots=True)
class ExportPlanItem:
    segment_id: uuid.UUID
    file_path: Path
    segment_start_at: datetime
    clip_start_at: datetime
    clip_end_at: datetime
    inpoint_seconds: float
    outpoint_seconds: float
    codec: str | None

    @property
    def duration_ms(self) -> int:
        return max(
            0,
            int(
                round(
                    (
                        self.clip_end_at - self.clip_start_at
                    ).total_seconds()
                    * 1000
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class ExportPlan:
    camera_id: uuid.UUID
    requested_start_at: datetime
    requested_end_at: datetime
    items: tuple[ExportPlanItem, ...]
    actual_duration_ms: int
    has_gaps: bool


class ExportPlanResolver:
    @staticmethod
    def _path(segment: RecordingSegment) -> Path | None:
        available = [
            location
            for location in segment.locations
            if location.state == "AVAILABLE"
        ]
        available.sort(
            key=lambda location: (
                0
                if location.storage_target.type == "local"
                else 1,
                str(location.id),
            )
        )
        for location in available:
            path = PlaybackResolverService.filesystem_path(
                location
            )
            if path is not None:
                return path
        return None

    @classmethod
    def build(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        start_at: datetime,
        end_at: datetime,
        gap_policy: str,
    ) -> ExportPlan:
        if end_at <= start_at:
            raise ApiError(
                status_code=400,
                code="invalid_time_range",
                message="Export range end must be after range start.",
            )
        if gap_policy not in {"skip", "fail"}:
            raise ApiError(
                status_code=400,
                code="export_gap_policy_invalid",
                message="Export gap policy must be skip or fail.",
            )

        segments = list(
            session.scalars(
                select(RecordingSegment)
                .options(
                    selectinload(
                        RecordingSegment.locations
                    ).joinedload(
                        RecordingLocation.storage_target
                    )
                )
                .where(
                    RecordingSegment.camera_id == camera_id,
                    RecordingSegment.started_at < end_at,
                    RecordingSegment.ended_at > start_at,
                )
                .order_by(
                    RecordingSegment.started_at,
                    RecordingSegment.ended_at,
                    RecordingSegment.id,
                )
            )
        )

        cursor = start_at
        items: list[ExportPlanItem] = []
        has_gaps = False

        for segment in segments:
            if segment.ended_at <= cursor:
                continue

            path = cls._path(segment)
            if path is None:
                continue

            clip_start = max(
                cursor,
                start_at,
                segment.started_at,
            )
            clip_end = min(
                end_at,
                segment.ended_at,
            )
            if clip_end <= clip_start:
                continue

            if clip_start > cursor:
                has_gaps = True
                if gap_policy == "fail":
                    raise ApiError(
                        status_code=409,
                        code="export_range_has_gaps",
                        message="Export range contains unavailable media.",
                        details={
                            "gap_start": cursor.isoformat(),
                            "gap_end": clip_start.isoformat(),
                        },
                    )

            inpoint = max(
                0.0,
                (
                    clip_start - segment.started_at
                ).total_seconds(),
            )
            outpoint = max(
                inpoint,
                (
                    clip_end - segment.started_at
                ).total_seconds(),
            )
            items.append(
                ExportPlanItem(
                    segment_id=segment.id,
                    file_path=path,
                    segment_start_at=segment.started_at,
                    clip_start_at=clip_start,
                    clip_end_at=clip_end,
                    inpoint_seconds=inpoint,
                    outpoint_seconds=outpoint,
                    codec=segment.codec,
                )
            )
            cursor = max(cursor, clip_end)
            if cursor >= end_at:
                break

        if cursor < end_at:
            has_gaps = True
            if gap_policy == "fail":
                raise ApiError(
                    status_code=409,
                    code="export_range_has_gaps",
                    message="Export range contains unavailable media.",
                    details={
                        "gap_start": cursor.isoformat(),
                        "gap_end": end_at.isoformat(),
                    },
                )

        if not items:
            raise ApiError(
                status_code=409,
                code="export_media_unavailable",
                message="No playable recording media exists in the selected range.",
            )

        actual_duration_ms = sum(
            item.duration_ms for item in items
        )
        return ExportPlan(
            camera_id=camera_id,
            requested_start_at=start_at,
            requested_end_at=end_at,
            items=tuple(items),
            actual_duration_ms=actual_duration_ms,
            has_gaps=has_gaps,
        )
