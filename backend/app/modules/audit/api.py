from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.modules.auth.dependencies import (
    get_effective_camera_scope,
    require_permission,
)
from app.modules.auth.service import AuthContext

from .models import AuditEvent
from .query import AuditQueryService, redact_audit_value
from .schemas import AuditEventView, AuditPage


router = APIRouter()


def _utc(
    value: datetime | None,
    *,
    field: str,
) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError(
            status_code=422,
            code="timezone_required",
            message=f"{field} must include a timezone offset.",
        )
    return value.astimezone(UTC)


def _view(item: AuditEvent) -> AuditEventView:
    return AuditEventView(
        id=item.id,
        occurred_at=item.occurred_at,
        actor_type=item.actor_type,
        actor_id=item.actor_id,
        action=item.action,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        camera_id=item.camera_id,
        request_id=item.request_id,
        correlation_id=item.correlation_id,
        source_ip=item.source_ip,
        client_info=redact_audit_value(
            item.client_info
        ),
        result=item.result,
        reason=item.reason,
        before=redact_audit_value(
            item.before_json
        ),
        after=redact_audit_value(
            item.after_json
        ),
        metadata=redact_audit_value(
            item.metadata_json
        ),
    )


@router.get(
    "",
    response_model=AuditPage,
)
def list_audit_events(
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    camera_id: uuid.UUID | None = None,
    result: str | None = None,
    from_at: datetime | None = Query(
        default=None,
        alias="from",
    ),
    to_at: datetime | None = Query(
        default=None,
        alias="to",
    ),
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    context: AuthContext = Depends(
        require_permission("audit.view")
    ),
    session: Session = Depends(get_db_session),
) -> AuditPage:
    scope = get_effective_camera_scope(
        context,
        session,
    )
    page = AuditQueryService.list(
        session,
        allowed_camera_ids=(
            None if scope.all_cameras
            else scope.camera_ids
        ),
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        camera_id=camera_id,
        result=result,
        from_at=_utc(from_at, field="from"),
        to_at=_utc(to_at, field="to"),
        cursor=cursor,
        limit=limit,
    )
    return AuditPage(
        items=[
            _view(item)
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )
