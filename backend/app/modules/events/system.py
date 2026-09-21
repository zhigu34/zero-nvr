from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Event


class SystemEventService:
    """Persist meaningful system-health transitions as canonical Events.

    V1 deliberately keeps source-connectivity incidents out of a dedicated
    table. A source outage is represented by one bounded Event interval whose
    start is the observed loss and whose end is the observed recovery.
    """

    SOURCE = "system"
    SOURCE_INSTANCE_ID = "zero-nvr"
    SOURCE_CONNECTIVITY_CATEGORY = "source_connectivity"
    SOURCE_LOST_LABEL = "source_lost"

    @staticmethod
    def _instant(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("system event timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @classmethod
    def is_source_loss(cls, event: Event) -> bool:
        return (
            event.source == cls.SOURCE
            and event.source_instance_id == cls.SOURCE_INSTANCE_ID
            and event.category == cls.SOURCE_CONNECTIVITY_CATEGORY
            and event.label == cls.SOURCE_LOST_LABEL
        )

    @classmethod
    def _open_source_loss(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
    ) -> Event | None:
        return session.scalar(
            select(Event)
            .where(
                Event.source == cls.SOURCE,
                Event.source_instance_id == cls.SOURCE_INSTANCE_ID,
                Event.camera_id == camera_id,
                Event.category == cls.SOURCE_CONNECTIVITY_CATEGORY,
                Event.label == cls.SOURCE_LOST_LABEL,
                Event.ended_at.is_(None),
            )
            .order_by(
                Event.started_at.desc(),
                Event.id.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def _metadata(
        *,
        stream: str,
        app: str,
        vhost: str,
    ) -> dict[str, Any]:
        return {
            "observer": "zlm_stream_changed",
            "source_app": app,
            "source_stream": stream,
            "source_vhost": vhost,
        }

    @classmethod
    def source_lost(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        observed_at: datetime,
        stream: str,
        app: str,
        vhost: str,
    ) -> Event:
        """Open one idempotent source-loss interval for a managed camera."""

        existing = cls._open_source_loss(
            session,
            camera_id=camera_id,
        )
        metadata = cls._metadata(
            stream=stream,
            app=app,
            vhost=vhost,
        )
        if existing is not None:
            existing.metadata_json = {
                **(existing.metadata_json or {}),
                **metadata,
            }
            session.flush()
            return existing

        event = Event(
            source=cls.SOURCE,
            source_instance_id=cls.SOURCE_INSTANCE_ID,
            camera_id=camera_id,
            category=cls.SOURCE_CONNECTIVITY_CATEGORY,
            label=cls.SOURCE_LOST_LABEL,
            started_at=cls._instant(observed_at),
            severity="warning",
            metadata_json=metadata,
        )
        session.add(event)
        session.flush()
        return event

    @classmethod
    def source_recovered(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        observed_at: datetime,
        stream: str,
        app: str,
        vhost: str,
    ) -> Event | None:
        """Close the current source-loss interval when ZLM registers again."""

        event = cls._open_source_loss(
            session,
            camera_id=camera_id,
        )
        if event is None:
            return None

        recovered_at = cls._instant(observed_at)
        if recovered_at < event.started_at:
            recovered_at = event.started_at

        event.ended_at = recovered_at
        event.metadata_json = {
            **(event.metadata_json or {}),
            "recovered_source_app": app,
            "recovered_source_stream": stream,
            "recovered_source_vhost": vhost,
        }
        session.flush()
        return event
