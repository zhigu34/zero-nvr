from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError

from .models import Event


@dataclass(frozen=True, slots=True)
class EventPageResult:
    items: list[Event]
    next_cursor: str | None


def _encode_cursor(event: Event) -> str:
    payload = json.dumps(
        {
            "started_at": event.started_at.astimezone(UTC).isoformat(),
            "id": str(event.id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(
                value + padding
            ).decode("utf-8")
        )
        started_at = datetime.fromisoformat(payload["started_at"])
        if (
            started_at.tzinfo is None
            or started_at.utcoffset() is None
        ):
            raise ValueError
        return (
            started_at.astimezone(UTC),
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
            code="event_cursor_invalid",
            message="Event cursor is invalid.",
        ) from exc


class EventQueryService:
    @staticmethod
    def get(
        session: Session,
        event_id: uuid.UUID,
    ) -> Event:
        event = session.get(Event, event_id)
        if event is None:
            raise ApiError(
                status_code=404,
                code="event_not_found",
                message="Event was not found.",
            )
        return event

    @staticmethod
    def list(
        session: Session,
        *,
        allowed_camera_ids: frozenset[uuid.UUID] | None,
        camera_id: uuid.UUID | None,
        start_at: datetime | None,
        end_at: datetime | None,
        source: str | None,
        category: str | None,
        label: str | None,
        zone: str | None,
        min_confidence: float | None,
        severity: str | None,
        cursor: str | None,
        limit: int,
    ) -> EventPageResult:
        if limit < 1 or limit > 200:
            raise ApiError(
                status_code=400,
                code="event_limit_invalid",
                message="Event limit must be between 1 and 200.",
            )
        if (
            start_at is not None
            and end_at is not None
            and end_at <= start_at
        ):
            raise ApiError(
                status_code=400,
                code="invalid_time_range",
                message="Event range end must be after range start.",
            )
        if min_confidence is not None and not 0 <= min_confidence <= 1:
            raise ApiError(
                status_code=400,
                code="event_confidence_invalid",
                message="Minimum confidence must be between 0 and 1.",
            )

        statement = select(Event)

        if camera_id is not None:
            statement = statement.where(Event.camera_id == camera_id)
        elif allowed_camera_ids is not None:
            statement = statement.where(
                or_(
                    Event.camera_id.is_(None),
                    Event.camera_id.in_(allowed_camera_ids),
                )
            )

        if start_at is not None:
            statement = statement.where(
                or_(
                    Event.ended_at.is_(None),
                    Event.ended_at > start_at,
                )
            )
        if end_at is not None:
            statement = statement.where(Event.started_at < end_at)
        if source:
            statement = statement.where(Event.source == source)
        if category:
            statement = statement.where(Event.category == category)
        if label:
            statement = statement.where(Event.label == label)
        if zone:
            statement = statement.where(Event.zone == zone)
        if severity:
            statement = statement.where(Event.severity == severity)
        if min_confidence is not None:
            statement = statement.where(
                Event.confidence >= min_confidence
            )

        if cursor is not None:
            cursor_started, cursor_id = _decode_cursor(cursor)
            statement = statement.where(
                or_(
                    Event.started_at < cursor_started,
                    and_(
                        Event.started_at == cursor_started,
                        Event.id < cursor_id,
                    ),
                )
            )

        rows = list(
            session.scalars(
                statement.order_by(
                    Event.started_at.desc(),
                    Event.id.desc(),
                ).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        return EventPageResult(
            items=items,
            next_cursor=(
                _encode_cursor(items[-1])
                if has_more and items
                else None
            ),
        )
