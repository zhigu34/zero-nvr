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


class TimelineRangeView(BaseModel):
    start_at: datetime
    end_at: datetime


class TimelineSegmentView(BaseModel):
    id: uuid.UUID
    start_at: datetime
    end_at: datetime
    availability: TimelineAvailability
    playback_ref: uuid.UUID


class TimelineGapView(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: TimelineGapReason


class TimelineEventView(BaseModel):
    id: str
    category: str
    label: str | None = None
    start_at: datetime
    end_at: datetime | None = None


class PlaybackTimelineView(BaseModel):
    camera_id: uuid.UUID
    range: TimelineRangeView
    segments: list[TimelineSegmentView]
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
