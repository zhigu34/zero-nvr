from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventView(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_type: str
    actor_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    camera_id: uuid.UUID | None
    request_id: str | None
    correlation_id: str | None
    source_ip: str | None
    client_info: dict[str, Any] | None
    result: str
    reason: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    metadata: dict[str, Any] | None


class AuditPage(BaseModel):
    items: list[AuditEventView]
    next_cursor: str | None
