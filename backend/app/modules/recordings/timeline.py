from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
    RecordingTrigger,
)
from app.modules.storage.models import RecordingLocation

from .schemas import (
    PlaybackTimelineView,
    TimelineGapView,
    TimelineRangeView,
    TimelineSegmentView,
)


_PLAYABLE = {"local", "remote", "cached_remote"}


@dataclass(frozen=True, slots=True)
class _ProjectedSegment:
    segment: RecordingSegment
    availability: str
    clipped_start: datetime
    clipped_end: datetime


class PlaybackTimelineService:
    @staticmethod
    def _availability(segment: RecordingSegment) -> str:
        if segment.integrity_status.upper() == "CORRUPT":
            return "corrupted"

        locations = segment.locations
        available = [
            item
            for item in locations
            if item.state == "AVAILABLE"
        ]

        if any(
            item.storage_target.type == "local"
            and item.storage_target.role == "recording"
            for item in available
        ):
            return "local"

        if any(
            item.storage_target.type == "rclone"
            and item.storage_target.role == "archive"
            for item in available
        ):
            return "remote"

        if any(item.state == "MISSING" for item in locations):
            return "missing"

        if locations and all(
            item.state == "DELETED"
            for item in locations
        ):
            return "purged"

        # Metadata exists but no known playable physical copy currently does.
        return "missing"

    @staticmethod
    def _unavailable_reason(
        projected: list[_ProjectedSegment],
    ) -> str:
        states = {item.availability for item in projected}
        if "corrupted" in states:
            return "storage_failure"
        if "missing" in states:
            return "missing_media"
        if states and states <= {"purged"}:
            return "purged"
        return "unknown"

    @staticmethod
    def _empty_reason(
        session: Session,
        *,
        camera_id: uuid.UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> str:
        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )
        if policy is None or not policy.enabled:
            return "not_scheduled"

        if (
            policy.baseline_mode == "disabled"
            and policy.event_recording_enabled
        ):
            trigger = session.scalar(
                select(RecordingTrigger.id)
                .where(
                    RecordingTrigger.camera_id == camera_id,
                    RecordingTrigger.state.notin_(["CANCELLED", "FAILED"]),
                    RecordingTrigger.planned_start_at < end_at,
                    or_(
                        RecordingTrigger.planned_end_at.is_(None),
                        RecordingTrigger.planned_end_at > start_at,
                    ),
                )
                .limit(1)
            )
            return "unknown" if trigger is not None else "no_event"

        if policy.baseline_mode == "disabled":
            return "not_scheduled"

        # Schedule evaluation and persisted source/runtime outage evidence refine
        # this later. Do not guess "source_lost" without actual evidence.
        return "unknown"

    @classmethod
    def build(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> PlaybackTimelineView:
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

        projected: list[_ProjectedSegment] = []
        response_segments: list[TimelineSegmentView] = []

        for segment in segments:
            availability = cls._availability(segment)
            clipped_start = max(segment.started_at, start_at)
            clipped_end = min(segment.ended_at, end_at)
            if clipped_end <= clipped_start:
                continue

            item = _ProjectedSegment(
                segment=segment,
                availability=availability,
                clipped_start=clipped_start,
                clipped_end=clipped_end,
            )
            projected.append(item)
            response_segments.append(
                TimelineSegmentView(
                    id=segment.id,
                    start_at=segment.started_at,
                    end_at=segment.ended_at,
                    availability=availability,
                    playback_ref=segment.id,
                )
            )

        boundaries = {start_at, end_at}
        for item in projected:
            boundaries.add(item.clipped_start)
            boundaries.add(item.clipped_end)
        ordered = sorted(boundaries)

        gaps: list[TimelineGapView] = []
        for left, right in zip(ordered, ordered[1:]):
            if right <= left:
                continue

            overlapping = [
                item
                for item in projected
                if item.clipped_start < right
                and item.clipped_end > left
            ]
            if any(
                item.availability in _PLAYABLE
                for item in overlapping
            ):
                continue

            if overlapping:
                reason = cls._unavailable_reason(overlapping)
            else:
                reason = cls._empty_reason(
                    session,
                    camera_id=camera_id,
                    start_at=left,
                    end_at=right,
                )

            if (
                gaps
                and gaps[-1].reason == reason
                and gaps[-1].end_at == left
            ):
                previous = gaps[-1]
                gaps[-1] = TimelineGapView(
                    start_at=previous.start_at,
                    end_at=right,
                    reason=reason,
                )
            else:
                gaps.append(
                    TimelineGapView(
                        start_at=left,
                        end_at=right,
                        reason=reason,
                    )
                )

        return PlaybackTimelineView(
            camera_id=camera_id,
            range=TimelineRangeView(
                start_at=start_at,
                end_at=end_at,
            ),
            segments=response_segments,
            gaps=gaps,
            # Event normalization/search is a separate module; the response
            # shape is frozen now so Event overlay can be added without an API
            # redesign.
            events=[],
        )
