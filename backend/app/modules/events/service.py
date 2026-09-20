from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.cameras.models import Camera

from .models import Event


@dataclass(frozen=True, slots=True)
class EventIngest:
    source: str
    category: str
    started_at: datetime
    source_instance_id: str | None = None
    source_event_id: str | None = None
    camera_id: uuid.UUID | None = None
    label: str | None = None
    ended_at: datetime | None = None
    confidence: float | None = None
    severity: str | None = None
    zone: str | None = None
    snapshot_ref: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EventUpsertResult:
    event: Event
    created: bool


class EventService:
    @staticmethod
    def _instant(value: datetime, *, field_name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ApiError(
                status_code=422,
                code="event_timezone_required",
                message=f"{field_name} must include a timezone offset.",
            )
        return value.astimezone(UTC)

    @staticmethod
    def _text(
        value: str | None,
        *,
        field_name: str,
        required: bool = False,
        max_length: int | None = None,
    ) -> str | None:
        if value is None:
            if required:
                raise ApiError(
                    status_code=422,
                    code="event_field_required",
                    message=f"{field_name} is required.",
                )
            return None
        normalized = value.strip()
        if required and not normalized:
            raise ApiError(
                status_code=422,
                code="event_field_required",
                message=f"{field_name} is required.",
            )
        if not normalized:
            return None
        if max_length is not None and len(normalized) > max_length:
            raise ApiError(
                status_code=422,
                code="event_field_too_long",
                message=f"{field_name} is too long.",
            )
        return normalized

    @classmethod
    def upsert_provider_event(
        cls,
        session: Session,
        *,
        item: EventIngest,
    ) -> EventUpsertResult:
        source = cls._text(
            item.source,
            field_name="source",
            required=True,
            max_length=64,
        )
        category = cls._text(
            item.category,
            field_name="category",
            required=True,
            max_length=64,
        )
        source_instance_id = cls._text(
            item.source_instance_id,
            field_name="source_instance_id",
            max_length=256,
        )
        source_event_id = cls._text(
            item.source_event_id,
            field_name="source_event_id",
            max_length=512,
        )
        if source_event_id is not None and source_instance_id is None:
            raise ApiError(
                status_code=422,
                code="event_source_instance_required",
                message="source_instance_id is required when source_event_id is provided.",
            )

        started_at = cls._instant(
            item.started_at,
            field_name="started_at",
        )
        ended_at = (
            cls._instant(item.ended_at, field_name="ended_at")
            if item.ended_at is not None
            else None
        )
        if ended_at is not None and ended_at < started_at:
            raise ApiError(
                status_code=422,
                code="event_time_range_invalid",
                message="Event end must not be before event start.",
            )

        if (
            item.confidence is not None
            and not 0 <= item.confidence <= 1
        ):
            raise ApiError(
                status_code=422,
                code="event_confidence_invalid",
                message="Event confidence must be between 0 and 1.",
            )

        if (
            item.camera_id is not None
            and session.get(Camera, item.camera_id) is None
        ):
            raise ApiError(
                status_code=422,
                code="event_camera_unknown",
                message="Event camera does not exist.",
            )

        existing: Event | None = None
        if source_event_id is not None:
            existing = session.scalar(
                select(Event).where(
                    Event.source == source,
                    Event.source_instance_id == source_instance_id,
                    Event.source_event_id == source_event_id,
                )
            )

        created = existing is None
        event = existing or Event(
            source=source,
            source_instance_id=source_instance_id,
            source_event_id=source_event_id,
            category=category,
            started_at=started_at,
        )

        if existing is not None:
            if (
                existing.camera_id is not None
                and item.camera_id is not None
                and existing.camera_id != item.camera_id
            ):
                raise ApiError(
                    status_code=409,
                    code="event_camera_identity_conflict",
                    message="Provider event identity is already mapped to another camera.",
                )
        else:
            session.add(event)

        event.camera_id = item.camera_id or event.camera_id
        event.category = category
        event.label = cls._text(
            item.label,
            field_name="label",
            max_length=128,
        )
        event.started_at = started_at
        event.ended_at = ended_at
        event.confidence = item.confidence
        event.severity = cls._text(
            item.severity,
            field_name="severity",
            max_length=32,
        )
        event.zone = cls._text(
            item.zone,
            field_name="zone",
            max_length=128,
        )
        event.snapshot_ref = cls._text(
            item.snapshot_ref,
            field_name="snapshot_ref",
        )
        event.correlation_id = cls._text(
            item.correlation_id,
            field_name="correlation_id",
            max_length=128,
        )
        event.metadata_json = dict(item.metadata)
        session.flush()

        return EventUpsertResult(
            event=event,
            created=created,
        )
