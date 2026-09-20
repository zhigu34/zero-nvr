from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


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



class ExportShareCreate(BaseModel):
    password: SecretStr | None = None
    expires_in_hours: int = Field(
        default=24,
        ge=1,
        le=720,
    )
    max_downloads: int | None = Field(
        default=None,
        ge=1,
        le=100000,
    )


class ExportShareView(BaseModel):
    id: uuid.UUID
    export_id: uuid.UUID
    expires_at: datetime
    revoked_at: datetime | None
    max_downloads: int | None
    download_count: int
    last_download_at: datetime | None
    password_protected: bool
    created_at: datetime


class ExportShareCreated(ExportShareView):
    token: str
    download_path: str
