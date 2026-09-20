from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditEvent


def append_audit_event(
    session: Session,
    *,
    request: Request,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    result: str = "success",
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    source_ip = None
    if request.client and request.client.host:
        source_ip = request.client.host[:64]

    user_agent = request.headers.get("user-agent")
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
        request_id=getattr(request.state, "request_id", None),
        source_ip=source_ip,
        client_info=client_info,
        result=result,
        reason=reason,
        before_json=before,
        after_json=after,
        metadata_json=metadata,
    )
    session.add(event)
    return event
