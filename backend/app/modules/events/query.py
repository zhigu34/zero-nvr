from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db.repository import fetch_or_404
from app.core.errors import ApiError
from app.core.pagination import Page, normalize_page_limit, paginate

from .models import Event


class EventQueryService:
    @staticmethod
    def get(
        session: Session,
        event_id: uuid.UUID,
    ) -> Event:
        event = fetch_or_404(
            session,
            Event,
            event_id,
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
    ) -> Page[Event]:
        normalize_page_limit(
            limit,
            error_code="event_limit_invalid",
            resource_label="Event",
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

        return paginate(
            session,
            statement,
            timestamp_column=Event.started_at,
            id_column=Event.id,
            cursor=cursor,
            limit=limit,
            cursor_key="started_at",
            cursor_error_code="event_cursor_invalid",
            resource_label="Event",
        )
