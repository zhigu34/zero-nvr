from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AlertPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    severity: Literal["info", "warning", "critical"] = "info"
    match: dict[str, object] = Field(default_factory=dict)
    actions: dict[str, object] = Field(default_factory=dict)
    cooldown_seconds: int = Field(default=0, ge=0, le=604800)


class AlertPolicyUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    enabled: bool | None = None
    severity: Literal["info", "warning", "critical"] | None = None
    match: dict[str, object] | None = None
    actions: dict[str, object] | None = None
    cooldown_seconds: int | None = Field(
        default=None,
        ge=0,
        le=604800,
    )


class AlertPolicyView(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    severity: Literal["info", "warning", "critical"]
    match: dict[str, object]
    actions: dict[str, object]
    cooldown_seconds: int
    created_at: datetime
    updated_at: datetime


class AlertView(BaseModel):
    id: uuid.UUID
    policy_id: uuid.UUID | None
    event_id: uuid.UUID
    camera_id: uuid.UUID | None
    severity: str
    title: str
    message: str | None
    state: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]
    acknowledged_at: datetime | None
    acknowledged_by: uuid.UUID | None
    resolved_at: datetime | None
    created_at: datetime


class AlertPage(BaseModel):
    items: list[AlertView]
    next_cursor: str | None = None
