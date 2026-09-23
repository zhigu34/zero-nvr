from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Event


@dataclass(frozen=True, slots=True)
class SystemHealthTransition:
    opened: Event | None = None
    closed: Event | None = None


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
    STORAGE_HEALTH_CATEGORY = "storage_health"
    RUNTIME_HEALTH_CATEGORY = "runtime_health"
    RUNTIME_RESTART_LABEL = "runtime_restart"

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
    def is_runtime_restart(cls, event: Event) -> bool:
        return (
            event.source == cls.SOURCE
            and event.source_instance_id == cls.SOURCE_INSTANCE_ID
            and event.category == cls.RUNTIME_HEALTH_CATEGORY
            and event.label == cls.RUNTIME_RESTART_LABEL
        )

    @classmethod
    def runtime_restarted(
        cls,
        session: Session,
        *,
        camera_ids: list[uuid.UUID],
        observed_at: datetime,
    ) -> tuple[Event, ...]:
        observed = cls._instant(observed_at)
        created: list[Event] = []
        for camera_id in sorted(
            set(camera_ids),
            key=str,
        ):
            event = Event(
                source=cls.SOURCE,
                source_instance_id=cls.SOURCE_INSTANCE_ID,
                camera_id=camera_id,
                category=cls.RUNTIME_HEALTH_CATEGORY,
                label=cls.RUNTIME_RESTART_LABEL,
                started_at=observed,
                ended_at=observed,
                severity="info",
                metadata_json={
                    "observer": "zlm_server_started",
                },
            )
            session.add(event)
            created.append(event)

        if created:
            session.flush()
        return tuple(created)

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
    def _open_storage_health(
        cls,
        session: Session,
        *,
        target_id: uuid.UUID,
    ) -> Event | None:
        return session.scalar(
            select(Event)
            .where(
                Event.source == cls.SOURCE,
                Event.source_instance_id
                == f"storage-target:{target_id}",
                Event.category == cls.STORAGE_HEALTH_CATEGORY,
                Event.ended_at.is_(None),
            )
            .order_by(
                Event.started_at.desc(),
                Event.id.desc(),
            )
            .limit(1)
        )

    @classmethod
    def storage_health_transition(
        cls,
        session: Session,
        *,
        target_id: uuid.UUID,
        target_name: str,
        observed_at: datetime,
        level: str,
        error_code: str | None = None,
        used_percent: float | None = None,
        free_bytes: int | None = None,
        total_bytes: int | None = None,
    ) -> SystemHealthTransition:
        """Persist only meaningful local-storage health transitions.

        Repeated observations at the same level are intentionally no-ops so
        periodic health checks do not become high-frequency database history.
        """

        normalized = level.strip().lower()
        if normalized not in {
            "ok",
            "warning",
            "high",
            "critical",
            "unavailable",
        }:
            raise ValueError("unsupported storage health level")

        observed = cls._instant(observed_at)
        existing = cls._open_storage_health(
            session,
            target_id=target_id,
        )

        closed: Event | None = None
        if existing is not None and (
            normalized == "ok"
            or existing.label != f"storage_{normalized}"
        ):
            existing.ended_at = max(
                existing.started_at,
                observed,
            )
            existing.metadata_json = {
                **(existing.metadata_json or {}),
                "recovered_at": existing.ended_at.isoformat(),
                "next_level": normalized,
            }
            closed = existing
            session.flush()

        if normalized == "ok":
            return SystemHealthTransition(
                closed=closed,
            )

        label = f"storage_{normalized}"
        if (
            existing is not None
            and closed is None
            and existing.label == label
        ):
            return SystemHealthTransition()

        metadata: dict[str, Any] = {
            "observer": "recording_capacity_guard",
            "storage_target_id": str(target_id),
            "storage_target_name": target_name,
            "level": normalized,
        }
        if error_code is not None:
            metadata["error_code"] = error_code
        if used_percent is not None:
            metadata["used_percent"] = round(
                float(used_percent),
                3,
            )
        if free_bytes is not None:
            metadata["free_bytes"] = int(free_bytes)
        if total_bytes is not None:
            metadata["total_bytes"] = int(total_bytes)

        event = Event(
            source=cls.SOURCE,
            source_instance_id=f"storage-target:{target_id}",
            source_event_id=(
                f"{label}:{uuid.uuid4()}"
            ),
            category=cls.STORAGE_HEALTH_CATEGORY,
            label=label,
            started_at=observed,
            severity=(
                "critical"
                if normalized in {"critical", "unavailable"}
                else "warning"
            ),
            correlation_id=f"storage-target:{target_id}",
            metadata_json=metadata,
        )
        session.add(event)
        session.flush()
        return SystemHealthTransition(
            opened=event,
            closed=closed,
        )

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
