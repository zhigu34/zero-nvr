from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ExportCreate(BaseModel):
    camera_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    format: Literal["mp4"] = "mp4"
    codec_mode: Literal["auto", "copy", "h264"] = "auto"
    gap_policy: Literal["skip", "fail"] = "skip"


class ExportView(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    requested_by: uuid.UUID | None
    start_at: datetime
    end_at: datetime
    requested_duration_ms: int
    format: str
    codec_mode: str
    gap_policy: str
    state: str
    size_bytes: int | None
    actual_duration_ms: int | None
    selected_segment_count: int | None
    metadata: dict[str, object]
    error_code: str | None
    expires_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ExportPage(BaseModel):
    items: list[ExportView]
    next_cursor: str | None
