from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import redact_sensitive_value

from .models import AuditEvent


def redact_audit_value(value: Any) -> Any:
    return redact_sensitive_value(value)


@dataclass(frozen=True, slots=True)
class AuditPageResult:
    items: list[AuditEvent]
    next_cursor: str | None


def _encode_cursor(item: AuditEvent) -> str:
    payload = json.dumps(
        {
            "occurred_at": item.occurred_at.astimezone(
                UTC
            ).isoformat(),
            "id": str(item.id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(
        payload
    ).decode("ascii").rstrip("=")


def _decode_cursor(
    value: str,
) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(
                value + padding
            ).decode("utf-8")
        )
        occurred = datetime.fromisoformat(
            payload["occurred_at"]
        )
        if (
            occurred.tzinfo is None
            or occurred.utcoffset() is None
        ):
            raise ValueError
        return (
            occurred.astimezone(UTC),
            uuid.UUID(payload["id"]),
        )
    except (
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raise ApiError(
            status_code=400,
            code="audit_cursor_invalid",
            message="Audit cursor is invalid.",
        ) from exc


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
    ) -> AuditPageResult:
        if limit < 1 or limit > 200:
            raise ApiError(
                status_code=400,
                code="audit_limit_invalid",
                message="Audit limit must be between 1 and 200.",
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
                AuditEvent.resource_id
                == resource_id
            )
        if camera_id is not None:
            if (
                allowed_camera_ids is not None
                and camera_id
                not in allowed_camera_ids
            ):
                return AuditPageResult(
                    items=[],
                    next_cursor=None,
                )
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

        if cursor is not None:
            occurred_at, audit_id = _decode_cursor(
                cursor
            )
            statement = statement.where(
                or_(
                    AuditEvent.occurred_at
                    < occurred_at,
                    and_(
                        AuditEvent.occurred_at
                        == occurred_at,
                        AuditEvent.id < audit_id,
                    ),
                )
            )

        rows = list(
            session.scalars(
                statement.order_by(
                    AuditEvent.occurred_at.desc(),
                    AuditEvent.id.desc(),
                ).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        return AuditPageResult(
            items=items,
            next_cursor=(
                _encode_cursor(items[-1])
                if has_more and items
                else None
            ),
        )
