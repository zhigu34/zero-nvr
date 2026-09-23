from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.events.models import Event
from app.modules.events.system import SystemEventService
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
    RecordingTrigger,
)
from app.modules.recordings.policy import (
    RecordingPolicyService,
)
from app.modules.storage.models import RecordingLocation
from app.modules.storage.recording_resolver import (
    RecordingStorageResolver,
)

from .playback_cache import PlaybackCacheService
from .schemas import (
    PlaybackTimelineView,
    TimelineDetailLevel,
    TimelineEventView,
    TimelineGapView,
    TimelineRangeView,
    TimelineRecordingRangeView,
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
    def _availability(
        segment: RecordingSegment,
        *,
        cache: PlaybackCacheService | None = None,
    ) -> str:
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

        remote_available = any(
            item.storage_target.type == "rclone"
            and item.storage_target.role == "archive"
            for item in available
        )
        if remote_available:
            if (
                cache is not None
                and cache.cached_file(
                    segment_id=segment.id,
                    expected_size=segment.size_bytes,
                    touch=False,
                )
                is not None
            ):
                return "cached_remote"
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
    def _recording_target_id(
        session: Session,
        *,
        camera_id: uuid.UUID,
    ) -> uuid.UUID | None:
        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id
                == camera_id
            )
        )
        if (
            policy is not None
            and policy.storage_target_id
            is not None
        ):
            return policy.storage_target_id

        try:
            return (
                RecordingStorageResolver
                .local_target_for_camera(
                    session,
                    camera_id=camera_id,
                )
                .target.id
            )
        except ApiError:
            return None

    @classmethod
    def _gap_evidence_events(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> list[Event]:
        camera_events = list(
            session.scalars(
                select(Event)
                .where(
                    Event.source
                    == SystemEventService.SOURCE,
                    Event.source_instance_id
                    == SystemEventService.SOURCE_INSTANCE_ID,
                    Event.camera_id == camera_id,
                    Event.category.in_(
                        [
                            SystemEventService
                            .SOURCE_CONNECTIVITY_CATEGORY,
                            SystemEventService
                            .RUNTIME_HEALTH_CATEGORY,
                        ]
                    ),
                    Event.started_at <= end_at,
                    or_(
                        Event.ended_at.is_(None),
                        Event.ended_at >= start_at,
                    ),
                )
                .order_by(
                    Event.started_at,
                    Event.id,
                )
            )
        )

        target_id = cls._recording_target_id(
            session,
            camera_id=camera_id,
        )
        if target_id is None:
            return camera_events

        storage_events = list(
            session.scalars(
                select(Event)
                .where(
                    Event.source
                    == SystemEventService.SOURCE,
                    Event.source_instance_id
                    == f"storage-target:{target_id}",
                    Event.category
                    == SystemEventService.STORAGE_HEALTH_CATEGORY,
                    Event.started_at < end_at,
                    or_(
                        Event.ended_at.is_(None),
                        Event.ended_at > start_at,
                    ),
                )
                .order_by(
                    Event.started_at,
                    Event.id,
                )
            )
        )
        return sorted(
            [*camera_events, *storage_events],
            key=lambda event: (
                event.started_at,
                str(event.id),
            ),
        )

    @classmethod
    def _empty_reason(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        start_at: datetime,
        end_at: datetime,
        policy: RecordingPolicy | None = None,
        evidence_events: list[Event] | None = None,
    ) -> str:
        if policy is None:
            policy = session.scalar(
                select(RecordingPolicy).where(
                    RecordingPolicy.camera_id
                    == camera_id
                )
            )
        if policy is None or not policy.enabled:
            return "not_scheduled"

        if policy.baseline_mode == "schedule":
            reference = start_at + (
                end_at - start_at
            ) / 2
            if not (
                RecordingPolicyService
                .baseline_should_record(
                    policy,
                    at=reference,
                )
            ):
                return "not_scheduled"

        if (
            policy.baseline_mode == "disabled"
            and policy.event_recording_enabled
        ):
            trigger = session.scalar(
                select(RecordingTrigger.id)
                .where(
                    RecordingTrigger.camera_id
                    == camera_id,
                    RecordingTrigger.state.notin_(
                        ["CANCELLED", "FAILED"]
                    ),
                    RecordingTrigger.planned_start_at
                    < end_at,
                    or_(
                        RecordingTrigger.planned_end_at
                        .is_(None),
                        RecordingTrigger.planned_end_at
                        > start_at,
                    ),
                )
                .limit(1)
            )
            if trigger is None:
                return "no_event"
        elif policy.baseline_mode == "disabled":
            return "not_scheduled"

        evidence = (
            evidence_events
            if evidence_events is not None
            else cls._gap_evidence_events(
                session,
                camera_id=camera_id,
                start_at=start_at,
                end_at=end_at,
            )
        )

        for event in evidence:
            if (
                SystemEventService
                .is_source_loss(event)
                and event.started_at < end_at
                and (
                    event.ended_at is None
                    or event.ended_at > start_at
                )
            ):
                return "source_lost"

        previous = session.scalar(
            select(RecordingSegment)
            .where(
                RecordingSegment.camera_id
                == camera_id,
                RecordingSegment.ended_at
                <= start_at,
            )
            .order_by(
                RecordingSegment.ended_at
                .desc(),
                RecordingSegment.id.desc(),
            )
            .limit(1)
        )
        if (
            previous is not None
            and (
                previous.completion_reason
                or ""
            ).lower()
            == "source_lost"
        ):
            return "source_lost"

        for event in evidence:
            if (
                SystemEventService
                .is_runtime_restart(event)
                and start_at
                <= event.started_at
                <= end_at
            ):
                return "runtime_restart"

        for event in evidence:
            if (
                event.category
                == SystemEventService.STORAGE_HEALTH_CATEGORY
                and event.label
                in {
                    "storage_critical",
                    "storage_unavailable",
                }
                and event.started_at < end_at
                and (
                    event.ended_at is None
                    or event.ended_at > start_at
                )
            ):
                return "storage_failure"

        # When no transition event survived, finalized segment evidence is the
        # safe fallback. Other outage causes remain unknown until proven.
        return "unknown"

    @staticmethod
    def _individual_event_marker(
        event: Event,
    ) -> TimelineEventView:
        marker_type = (
            "range"
            if (
                event.ended_at is None
                or event.ended_at
                > event.started_at
            )
            else "point"
        )
        label_counts = (
            {event.label: 1}
            if event.label
            else {}
        )
        return TimelineEventView(
            id=str(event.id),
            marker_type=marker_type,
            category=event.category,
            label=event.label,
            start_at=event.started_at,
            end_at=event.ended_at,
            count=1,
            category_counts={
                event.category: 1
            },
            label_counts=label_counts,
        )

    @classmethod
    def _event_markers(
        cls,
        events: list[Event],
        *,
        start_at: datetime,
        end_at: datetime,
        detail: TimelineDetailLevel,
    ) -> list[TimelineEventView]:
        if detail == "minute":
            return [
                cls._individual_event_marker(
                    event
                )
                for event in events
            ]

        bucket_size = timedelta(
            hours=1
            if detail == "day"
            else 0,
            minutes=0
            if detail == "day"
            else 5,
        )
        bucket_seconds = int(
            bucket_size.total_seconds()
        )
        start_epoch = int(
            start_at.timestamp()
        )
        cursor_epoch = (
            start_epoch
            - (
                start_epoch
                % bucket_seconds
            )
        )
        markers: list[
            TimelineEventView
        ] = []

        while True:
            bucket_start = datetime.fromtimestamp(
                cursor_epoch,
                tz=UTC,
            )
            if bucket_start >= end_at:
                break

            bucket_end = (
                bucket_start
                + bucket_size
            )
            matching: list[Event] = []
            for event in events:
                event_end = (
                    event.ended_at
                    if event.ended_at is not None
                    else end_at
                )
                is_point = (
                    event.ended_at is not None
                    and event.ended_at
                    <= event.started_at
                )
                if is_point:
                    overlaps = (
                        bucket_start
                        <= event.started_at
                        < bucket_end
                    )
                else:
                    overlaps = (
                        event.started_at
                        < bucket_end
                        and event_end
                        > bucket_start
                    )
                if overlaps:
                    matching.append(event)

            if matching:
                category_counts = Counter(
                    event.category
                    for event in matching
                )
                label_counts = Counter(
                    event.label
                    for event in matching
                    if event.label
                )
                categories = sorted(
                    category_counts
                )
                labels = sorted(
                    label_counts
                )
                category = (
                    categories[0]
                    if len(categories) == 1
                    else "events"
                )
                label = (
                    labels[0]
                    if (
                        len(labels) == 1
                        and sum(
                            label_counts.values()
                        )
                        == len(matching)
                    )
                    else None
                )
                marker_start = max(
                    bucket_start,
                    start_at,
                )
                marker_end = min(
                    bucket_end,
                    end_at,
                )
                markers.append(
                    TimelineEventView(
                        id=(
                            f"aggregate:{detail}:"
                            f"{cursor_epoch}"
                        ),
                        marker_type="aggregate",
                        category=category,
                        label=label,
                        start_at=marker_start,
                        end_at=marker_end,
                        count=len(matching),
                        category_counts=dict(
                            sorted(
                                category_counts
                                .items()
                            )
                        ),
                        label_counts=dict(
                            sorted(
                                label_counts
                                .items()
                            )
                        ),
                    )
                )

            cursor_epoch += (
                bucket_seconds
            )

        return markers

    @classmethod
    def build(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        start_at: datetime,
        end_at: datetime,
        detail: TimelineDetailLevel = "minute",
        settings: Settings | None = None,
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

        timeline_events = list(
            session.scalars(
                select(Event)
                .where(
                    Event.camera_id == camera_id,
                    Event.started_at < end_at,
                    or_(
                        Event.started_at >= start_at,
                        Event.ended_at.is_(None),
                        Event.ended_at > start_at,
                    ),
                )
                .order_by(
                    Event.started_at,
                    Event.id,
                )
            )
        )

        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id
                == camera_id
            )
        )
        gap_evidence_events = (
            cls._gap_evidence_events(
                session,
                camera_id=camera_id,
                start_at=start_at,
                end_at=end_at,
            )
        )

        projected: list[_ProjectedSegment] = []
        cache = (
            PlaybackCacheService(settings)
            if settings is not None
            else None
        )

        for segment in segments:
            availability = cls._availability(
                segment,
                cache=cache,
            )
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

        boundaries = {start_at, end_at}
        for item in projected:
            boundaries.add(item.clipped_start)
            boundaries.add(item.clipped_end)

        if (
            policy is not None
            and policy.enabled
            and policy.baseline_mode
            == "schedule"
        ):
            cursor = start_at
            for _ in range(4096):
                transition = (
                    RecordingPolicyService
                    .next_baseline_transition(
                        policy,
                        after=cursor,
                    )
                )
                if (
                    transition is None
                    or transition >= end_at
                ):
                    break
                if transition > start_at:
                    boundaries.add(transition)
                cursor = transition

        for event in gap_evidence_events:
            if start_at < event.started_at < end_at:
                boundaries.add(event.started_at)
            if (
                event.ended_at is not None
                and start_at
                < event.ended_at
                < end_at
            ):
                boundaries.add(event.ended_at)

        # Connectivity transitions split otherwise-empty ranges so a recovered
        # outage is not painted beyond its observed interval.
        for event in timeline_events:
            if not SystemEventService.is_source_loss(event):
                continue
            if start_at < event.started_at < end_at:
                boundaries.add(event.started_at)
            if (
                event.ended_at is not None
                and start_at < event.ended_at < end_at
            ):
                boundaries.add(event.ended_at)

        ordered = sorted(boundaries)

        recording_ranges: list[TimelineRecordingRangeView] = []
        gaps: list[TimelineGapView] = []
        availability_priority = {
            "local": 6,
            "cached_remote": 5,
            "remote": 4,
            "corrupted": 3,
            "missing": 2,
            "purged": 1,
        }

        for left, right in zip(ordered, ordered[1:]):
            if right <= left:
                continue

            overlapping = [
                item
                for item in projected
                if item.clipped_start < right
                and item.clipped_end > left
            ]
            if overlapping:
                availability = max(
                    (
                        item.availability
                        for item in overlapping
                    ),
                    key=lambda value: availability_priority[value],
                )
                if (
                    recording_ranges
                    and recording_ranges[-1].availability == availability
                    and recording_ranges[-1].end_at == left
                ):
                    previous = recording_ranges[-1]
                    recording_ranges[-1] = TimelineRecordingRangeView(
                        start_at=previous.start_at,
                        end_at=right,
                        availability=availability,
                    )
                else:
                    recording_ranges.append(
                        TimelineRecordingRangeView(
                            start_at=left,
                            end_at=right,
                            availability=availability,
                        )
                    )

                if availability in _PLAYABLE:
                    continue
                reason = cls._unavailable_reason(overlapping)
            else:
                reason = cls._empty_reason(
                    session,
                    camera_id=camera_id,
                    start_at=left,
                    end_at=right,
                    policy=policy,
                    evidence_events=(
                        gap_evidence_events
                    ),
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
            detail=detail,
            range=TimelineRangeView(
                start_at=start_at,
                end_at=end_at,
            ),
            recording_ranges=recording_ranges,
            gaps=gaps,
            events=cls._event_markers(
                timeline_events,
                start_at=start_at,
                end_at=end_at,
                detail=detail,
            ),
        )
