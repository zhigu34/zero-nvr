from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class NotificationTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    config: dict[str, object] = Field(default_factory=dict)
    url: SecretStr


class NotificationTargetUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    enabled: bool | None = None
    config: dict[str, object] | None = None
    url: SecretStr | None = None


class NotificationTargetView(BaseModel):
    id: uuid.UUID
    name: str
    kind: Literal["apprise"]
    enabled: bool
    config: dict[str, object]
    url_configured: bool


class NotificationTargetTestView(BaseModel):
    ok: Literal[True] = True


class NotificationDeliveryView(BaseModel):
    id: uuid.UUID
    alert_id: uuid.UUID
    notification_target_id: uuid.UUID
    state: Literal[
        "PENDING",
        "SENDING",
        "SENT",
        "FAILED",
        "SKIPPED",
    ]
    attempts: int
    title: str
    body: str
    last_attempt_at: datetime | None
    delivered_at: datetime | None
    last_error_code: str | None
    created_at: datetime
