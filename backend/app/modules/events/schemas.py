from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class EventView(BaseModel):
    id: uuid.UUID
    source: str
    source_instance_id: str | None
    source_event_id: str | None
    camera_id: uuid.UUID | None
    category: str
    label: str | None
    started_at: datetime
    ended_at: datetime | None
    confidence: float | None
    severity: str | None
    zone: str | None
    snapshot_ref: str | None
    correlation_id: str | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class EventPage(BaseModel):
    items: list[EventView]
    next_cursor: str | None = None
