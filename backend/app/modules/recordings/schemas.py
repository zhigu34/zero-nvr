from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
