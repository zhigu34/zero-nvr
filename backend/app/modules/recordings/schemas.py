from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TimelineAvailability = Literal[
    "local",
    "remote",
    "cached_remote",
    "missing",
    "corrupted",
    "purged",
]

TimelineGapReason = Literal[
    "not_scheduled",
    "no_event",
    "source_lost",
    "runtime_restart",
    "storage_failure",
    "missing_media",
    "purged",
    "unknown",
]

TimelineDetailLevel = Literal[
    "day",
    "hour",
    "minute",
]

TimelineEventMarkerType = Literal[
    "point",
    "range",
    "aggregate",
]


class TimelineRangeView(BaseModel):
    start_at: datetime
    end_at: datetime


class TimelineRecordingRangeView(BaseModel):
    start_at: datetime
    end_at: datetime
    availability: TimelineAvailability


class TimelineSegmentView(BaseModel):
    id: uuid.UUID
    playback_ref: uuid.UUID
    start_at: datetime
    end_at: datetime
    availability: TimelineAvailability


class TimelineGapView(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: TimelineGapReason


class TimelineEventView(BaseModel):
    id: str
    marker_type: TimelineEventMarkerType
    category: str
    label: str | None = None
    start_at: datetime
    end_at: datetime | None = None
    count: int = 1
    category_counts: dict[str, int] = Field(
        default_factory=dict
    )
    label_counts: dict[str, int] = Field(
        default_factory=dict
    )


class PlaybackTimelineView(BaseModel):
    camera_id: uuid.UUID
    detail: TimelineDetailLevel
    range: TimelineRangeView
    segments: list[TimelineSegmentView]
    recording_ranges: list[TimelineRecordingRangeView]
    gaps: list[TimelineGapView]
    events: list[TimelineEventView]



class RecordingPolicyPut(BaseModel):
    baseline_mode: Literal["continuous", "schedule", "disabled"]
    schedule: dict[str, object] = Field(default_factory=dict)
    schedule_timezone: str | None = None
    event_recording_enabled: bool = False
    event_filter: dict[str, object] = Field(default_factory=dict)
    segment_target_seconds: int = 300
    pre_roll_seconds: int = 10
    post_roll_seconds: int = 10
    storage_target_id: uuid.UUID | None = None
    retention_policy_id: uuid.UUID | None = None
    enabled: bool = True


class RecordingRuntimeView(BaseModel):
    desired_mode: Literal["persistent", "prebuffer", "off"]
    recording: bool
    changed: bool
    assumed_existing_mode: bool


class RecordingPolicyView(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    baseline_mode: Literal["continuous", "schedule", "disabled"]
    schedule: dict[str, object]
    schedule_timezone: str | None
    event_recording_enabled: bool
    event_filter: dict[str, object]
    segment_target_seconds: int
    pre_roll_seconds: int
    post_roll_seconds: int
    storage_target_id: uuid.UUID | None
    retention_policy_id: uuid.UUID | None
    enabled: bool
    runtime: RecordingRuntimeView | None = None



class RecordingTriggerCreate(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class RecordingTriggerView(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    type: str
    source: str
    requested_at: datetime
    pre_roll_seconds: int
    post_roll_seconds: int
    planned_start_at: datetime
    planned_end_at: datetime | None
    state: str
    reason: str | None
    correlation_id: str



class RecordingSegmentView(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    stream_profile_id: uuid.UUID | None
    start_at: datetime
    end_at: datetime
    duration_ms: int
    timing_status: str
    timing_source: str
    recording_reasons: list[str]
    size_bytes: int
    codec: str | None
    container: str
    integrity_status: str
    completion_reason: str | None
    created_at: datetime


class RecordingLocationView(BaseModel):
    id: uuid.UUID
    recording_segment_id: uuid.UUID
    storage_target_id: uuid.UUID
    storage_target_name: str
    storage_type: str
    storage_role: str
    object_path: str
    state: str
    size_bytes: int
    checksum: str | None
    verified_at: datetime | None
    created_at: datetime
    deleted_at: datetime | None


class RecordingSegmentPage(BaseModel):
    items: list[RecordingSegmentView]
    next_cursor: str | None = None



class PlaybackResolveRequest(BaseModel):
    at: datetime


class PlaybackSegmentResolveRequest(BaseModel):
    offset_ms: int = Field(
        default=0,
        ge=0,
    )


class PlaybackPlayableView(BaseModel):
    status: Literal["playable"] = "playable"
    segment_id: uuid.UUID
    segment_start_at: datetime
    offset_ms: int
    transport: Literal["fmp4"] = "fmp4"
    url: str
    expires_at: datetime
    codec: str | None = None


class PlaybackPendingView(BaseModel):
    status: Literal["pending"] = "pending"
    reason: Literal["remote_restore_required"]
    segment_id: uuid.UUID
    retry_after_ms: int = 2000


class PlaybackGapView(BaseModel):
    status: Literal["gap"] = "gap"
    reason: str
    previous_at: datetime | None = None
    next_at: datetime | None = None


PlaybackResolveView = (
    PlaybackPlayableView
    | PlaybackPendingView
    | PlaybackGapView
)



class RecordingProtectionCreate(BaseModel):
    started_at: datetime
    ended_at: datetime
    reason: str = Field(min_length=1, max_length=1024)
    expires_at: datetime | None = None


class RecordingProtectionUpdate(BaseModel):
    started_at: datetime
    ended_at: datetime
    reason: str = Field(min_length=1, max_length=1024)
    expires_at: datetime | None = None


class RecordingProtectionView(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    reason: str
    created_by: uuid.UUID | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
