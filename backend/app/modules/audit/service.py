from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.security import redact_sensitive_value, redact_text

from .models import AuditEvent


def append_audit_event(
    session: Session,
    *,
    request: Request | None,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    camera_id: uuid.UUID | None = None,
    result: str = "success",
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    source_ip = None
    if (
        request is not None
        and request.client
        and request.client.host
    ):
        source_ip = request.client.host[:64]

    user_agent = (
        request.headers.get("user-agent")
        if request is not None
        else None
    )
    client_info = (
        {"user_agent": user_agent[:512]}
        if user_agent
        else None
    )

    event = AuditEvent(
        actor_type="user" if actor_id else "system",
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        camera_id=camera_id,
        request_id=(
            getattr(request.state, "request_id", None)
            if request is not None
            else None
        ),
        source_ip=source_ip,
        client_info=redact_sensitive_value(client_info),
        result=result,
        reason=(redact_text(reason) if reason is not None else None),
        before_json=redact_sensitive_value(before),
        after_json=redact_sensitive_value(after),
        metadata_json=redact_sensitive_value(metadata),
    )
    session.add(event)
    return event
