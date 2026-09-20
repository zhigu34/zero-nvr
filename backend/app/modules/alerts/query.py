from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError

from .models import Alert


@dataclass(frozen=True, slots=True)
class AlertPageResult:
    items: list[Alert]
    next_cursor: str | None


def _encode_cursor(item: Alert) -> str:
    payload = json.dumps(
        {
            "created_at": item.created_at.astimezone(UTC).isoformat(),
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
        created_at = datetime.fromisoformat(
            payload["created_at"]
        )
        if (
            created_at.tzinfo is None
            or created_at.utcoffset() is None
        ):
            raise ValueError
        return (
            created_at.astimezone(UTC),
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
            code="alert_cursor_invalid",
            message="Alert cursor is invalid.",
        ) from exc


class AlertQueryService:
    @staticmethod
    def get(
        session: Session,
        alert_id: uuid.UUID,
    ) -> Alert:
        alert = session.get(Alert, alert_id)
        if alert is None:
            raise ApiError(
                status_code=404,
                code="alert_not_found",
                message="Alert was not found.",
            )
        return alert

    @staticmethod
    def list(
        session: Session,
        *,
        allowed_camera_ids: frozenset[uuid.UUID] | None,
        camera_id: uuid.UUID | None,
        state: str | None,
        severity: str | None,
        cursor: str | None,
        limit: int,
    ) -> AlertPageResult:
        if limit < 1 or limit > 200:
            raise ApiError(
                status_code=400,
                code="alert_limit_invalid",
                message="Alert limit must be between 1 and 200.",
            )

        statement = select(Alert)
        if camera_id is not None:
            statement = statement.where(
                Alert.camera_id == camera_id
            )
        elif allowed_camera_ids is not None:
            statement = statement.where(
                or_(
                    Alert.camera_id.is_(None),
                    Alert.camera_id.in_(
                        allowed_camera_ids
                    ),
                )
            )

        if state:
            if state not in {
                "OPEN",
                "ACKNOWLEDGED",
                "RESOLVED",
            }:
                raise ApiError(
                    status_code=400,
                    code="alert_state_invalid",
                    message="Alert state is invalid.",
                )
            statement = statement.where(
                Alert.state == state
            )

        if severity:
            statement = statement.where(
                Alert.severity == severity
            )

        if cursor is not None:
            created_at, alert_id = _decode_cursor(
                cursor
            )
            statement = statement.where(
                or_(
                    Alert.created_at < created_at,
                    and_(
                        Alert.created_at == created_at,
                        Alert.id < alert_id,
                    ),
                )
            )

        rows = list(
            session.scalars(
                statement.order_by(
                    Alert.created_at.desc(),
                    Alert.id.desc(),
                ).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        return AlertPageResult(
            items=items,
            next_cursor=(
                _encode_cursor(items[-1])
                if has_more and items
                else None
            ),
        )
