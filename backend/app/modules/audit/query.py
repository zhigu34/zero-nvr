from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.pagination import Page, normalize_page_limit, paginate
from app.core.security import redact_sensitive_value

from .models import AuditEvent


def redact_audit_value(value: Any) -> Any:
    return redact_sensitive_value(value)


class AuditQueryService:
    @staticmethod
    def list(
        session: Session,
        *,
        allowed_camera_ids: frozenset[uuid.UUID] | None,
        actor_id: uuid.UUID | None,
        action: str | None,
        resource_type: str | None,
        resource_id: uuid.UUID | None,
        camera_id: uuid.UUID | None,
        result: str | None,
        from_at: datetime | None,
        to_at: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> Page[AuditEvent]:
        normalize_page_limit(
            limit,
            error_code="audit_limit_invalid",
            resource_label="Audit",
        )
        if (
            from_at is not None
            and to_at is not None
            and to_at <= from_at
        ):
            raise ApiError(
                status_code=400,
                code="invalid_time_range",
                message="Audit range end must be after range start.",
            )

        statement = select(AuditEvent)
        if allowed_camera_ids is not None:
            if allowed_camera_ids:
                statement = statement.where(
                    or_(
                        AuditEvent.camera_id.is_(None),
                        AuditEvent.camera_id.in_(
                            allowed_camera_ids
                        ),
                    )
                )
            else:
                statement = statement.where(
                    AuditEvent.camera_id.is_(None)
                )

        if actor_id is not None:
            statement = statement.where(
                AuditEvent.actor_id == actor_id
            )
        if action is not None:
            statement = statement.where(
                AuditEvent.action == action
            )
        if resource_type is not None:
            statement = statement.where(
                AuditEvent.resource_type
                == resource_type
            )
        if resource_id is not None:
            statement = statement.where(
                AuditEvent.resource_id == resource_id
            )
        if camera_id is not None:
            if (
                allowed_camera_ids is not None
                and camera_id
                not in allowed_camera_ids
            ):
                # The requested camera is outside the caller's scope. Returning
                # an empty page (rather than 404) keeps the endpoint from
                # confirming that the camera exists.
                return Page(items=[], next_cursor=None)
            statement = statement.where(
                AuditEvent.camera_id == camera_id
            )
        if result is not None:
            statement = statement.where(
                AuditEvent.result == result
            )
        if from_at is not None:
            statement = statement.where(
                AuditEvent.occurred_at >= from_at
            )
        if to_at is not None:
            statement = statement.where(
                AuditEvent.occurred_at < to_at
            )

        return paginate(
            session,
            statement,
            timestamp_column=AuditEvent.occurred_at,
            id_column=AuditEvent.id,
            cursor=cursor,
            limit=limit,
            cursor_key="occurred_at",
            cursor_error_code="audit_cursor_invalid",
            resource_label="Audit",
        )
