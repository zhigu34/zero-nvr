from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class SmtpCredentialsInput(BaseModel):
    username: str = Field(
        min_length=1,
        max_length=320,
    )
    password: SecretStr


class NotificationTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: Literal["apprise", "smtp"] = "apprise"
    enabled: bool = True
    config: dict[str, object] = Field(default_factory=dict)
    url: SecretStr | None = None
    smtp_credentials: SmtpCredentialsInput | None = None


class NotificationTargetUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    enabled: bool | None = None
    config: dict[str, object] | None = None
    url_action: Literal[
        "keep",
        "replace",
        "clear",
    ] = "keep"
    url: SecretStr | None = None
    credentials_action: Literal[
        "keep",
        "replace",
        "clear",
    ] = "keep"
    smtp_credentials: SmtpCredentialsInput | None = None


class NotificationTargetView(BaseModel):
    id: uuid.UUID
    name: str
    kind: Literal["apprise", "smtp"]
    enabled: bool
    config: dict[str, object]
    url_configured: bool
    credentials_configured: bool


class SecurityEmailTargetUpdate(BaseModel):
    target_id: uuid.UUID | None


class SecurityEmailTargetView(BaseModel):
    target_id: uuid.UUID | None


class NotificationTargetTestView(BaseModel):
    ok: Literal[True] = True


class NotificationDeliveryView(BaseModel):
    id: uuid.UUID
    alert_id: uuid.UUID | None
    purpose: Literal[
        "alert",
        "password_reset",
        "security",
        "system_test",
    ]
    notification_target_id: uuid.UUID
    state: Literal[
        "PENDING",
        "SENDING",
        "SENT",
        "FAILED",
        "SKIPPED",
    ]
    attempt_count: int
    title: str
    body: str
    last_attempt_at: datetime | None
    sent_at: datetime | None
    last_error_code: str | None
    provider_message_id: str | None
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime
