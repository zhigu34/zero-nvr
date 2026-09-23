from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Database
from app.integrations.onvif.normalizer import (
    OnvifNormalizedNotification,
    normalize_onvif_notification,
)
from app.modules.cameras.models import (
    Camera,
    CameraStreamProfile,
    Device,
)

from .models import Event
from .service import EventIngest, EventService


@dataclass(frozen=True, slots=True)
class OnvifEventIngestResult:
    created: int = 0
    updated: int = 0
    closed: int = 0
    ignored: int = 0


class OnvifEventIngestService:
    SOURCE = "onvif"

    def __init__(
        self,
        database: Database,
        *,
        logger: logging.Logger,
    ) -> None:
        self.database = database
        self.logger = logger

    @staticmethod
    def _source_instance_id(
        device_id: uuid.UUID,
    ) -> str:
        return f"device:{device_id}"

    @staticmethod
    def _source_tokens(
        normalized: OnvifNormalizedNotification,
    ) -> tuple[str, ...]:
        preferred_names = {
            "videosourcetoken",
            "videosourceconfigurationtoken",
            "sourcetoken",
            "source",
            "profiletoken",
            "profile",
        }
        tokens: list[str] = []
        for name, value in normalized.source_items.items():
            if (
                name.casefold() in preferred_names
                and value not in tokens
            ):
                tokens.append(value)
        return tuple(tokens)

    @classmethod
    def _camera_id(
        cls,
        session: Session,
        *,
        device_id: uuid.UUID,
        normalized: OnvifNormalizedNotification,
    ) -> uuid.UUID | None:
        cameras = list(
            session.scalars(
                select(Camera)
                .where(
                    Camera.device_id == device_id,
                    Camera.retired_at.is_(None),
                )
                .order_by(Camera.id)
            )
        )
        if not cameras:
            return None

        tokens = cls._source_tokens(
            normalized
        )
        for token in tokens:
            direct = next(
                (
                    camera
                    for camera in cameras
                    if camera.channel_key == token
                ),
                None,
            )
            if direct is not None:
                return direct.id

        if tokens:
            profile_camera_id = session.scalar(
                select(
                    CameraStreamProfile.camera_id
                )
                .join(
                    Camera,
                    Camera.id
                    == CameraStreamProfile.camera_id,
                )
                .where(
                    Camera.device_id == device_id,
                    Camera.retired_at.is_(None),
                    (
                        CameraStreamProfile.video_source_key.in_(
                            tokens
                        )
                        | CameraStreamProfile.adapter_profile_key.in_(
                            tokens
                        )
                    ),
                )
                .order_by(
                    CameraStreamProfile.camera_id
                )
                .limit(1)
            )
            if profile_camera_id is not None:
                return profile_camera_id

        if len(cameras) == 1:
            return cameras[0].id
        return None

    @classmethod
    def _open_event(
        cls,
        session: Session,
        *,
        source_instance_id: str,
        camera_id: uuid.UUID | None,
        normalized: OnvifNormalizedNotification,
    ) -> Event | None:
        statement = (
            select(Event)
            .where(
                Event.source == cls.SOURCE,
                Event.source_instance_id
                == source_instance_id,
                Event.category
                == normalized.category,
                Event.label
                == normalized.label,
                Event.ended_at.is_(None),
            )
            .order_by(
                Event.started_at.desc(),
                Event.id.desc(),
            )
        )
        if camera_id is None:
            statement = statement.where(
                Event.camera_id.is_(None)
            )
        else:
            statement = statement.where(
                Event.camera_id == camera_id
            )

        for event in session.scalars(
            statement
        ):
            if (
                (event.metadata_json or {}).get(
                    "topic"
                )
                == normalized.topic
            ):
                return event
        return None

    @classmethod
    def _provider_event(
        cls,
        session: Session,
        *,
        source_instance_id: str,
        source_event_id: str,
    ) -> Event | None:
        return session.scalar(
            select(Event).where(
                Event.source == cls.SOURCE,
                Event.source_instance_id
                == source_instance_id,
                Event.source_event_id
                == source_event_id,
            )
        )

    @staticmethod
    def _metadata(
        normalized: OnvifNormalizedNotification,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "topic": normalized.topic,
            "source_items": (
                normalized.source_items
            ),
            "data_items": normalized.data_items,
        }
        if normalized.property_operation:
            result["property_operation"] = (
                normalized.property_operation
            )
        if normalized.state is not None:
            result["state"] = normalized.state
        return result

    @classmethod
    def _ingest_one(
        cls,
        session: Session,
        *,
        device_id: uuid.UUID,
        normalized: OnvifNormalizedNotification,
    ) -> tuple[str, Event | None]:
        source_instance_id = (
            cls._source_instance_id(
                device_id
            )
        )
        camera_id = cls._camera_id(
            session,
            device_id=device_id,
            normalized=normalized,
        )
        existing = cls._open_event(
            session,
            source_instance_id=source_instance_id,
            camera_id=camera_id,
            normalized=normalized,
        )

        if normalized.state is False:
            if existing is None:
                return "ignored", None
            existing.ended_at = max(
                existing.started_at,
                normalized.occurred_at,
            )
            existing.metadata_json = {
                **(existing.metadata_json or {}),
                **cls._metadata(normalized),
            }
            session.flush()
            return "closed", existing

        if normalized.state is True and existing is None:
            replayed = cls._provider_event(
                session,
                source_instance_id=source_instance_id,
                source_event_id=(
                    normalized.source_event_id
                ),
            )
            if (
                replayed is not None
                and replayed.ended_at is not None
            ):
                replayed.metadata_json = {
                    **(replayed.metadata_json or {}),
                    **cls._metadata(normalized),
                    "replayed_after_close": True,
                }
                session.flush()
                return "updated", replayed

        if normalized.state is True and existing is not None:
            result = EventService.upsert_provider_event(
                session,
                item=EventIngest(
                    source=cls.SOURCE,
                    source_instance_id=source_instance_id,
                    source_event_id=existing.source_event_id,
                    camera_id=camera_id,
                    category=normalized.category,
                    label=normalized.label,
                    started_at=existing.started_at,
                    severity="info",
                    correlation_id=(
                        existing.correlation_id
                        or existing.source_event_id
                    ),
                    metadata={
                        **(existing.metadata_json or {}),
                        **cls._metadata(normalized),
                    },
                ),
            )
            return "updated", result.event

        ended_at = (
            normalized.occurred_at
            if normalized.state is None
            else None
        )
        result = EventService.upsert_provider_event(
            session,
            item=EventIngest(
                source=cls.SOURCE,
                source_instance_id=source_instance_id,
                source_event_id=(
                    normalized.source_event_id
                ),
                camera_id=camera_id,
                category=normalized.category,
                label=normalized.label,
                started_at=normalized.occurred_at,
                ended_at=ended_at,
                severity="info",
                correlation_id=(
                    normalized.source_event_id
                ),
                metadata=cls._metadata(
                    normalized
                ),
            ),
        )
        return (
            "created"
            if result.created
            else "updated",
            result.event,
        )

    def handle(
        self,
        device_id: uuid.UUID,
        notifications: tuple[Any, ...],
    ) -> OnvifEventIngestResult:
        counters = {
            "created": 0,
            "updated": 0,
            "closed": 0,
            "ignored": 0,
        }
        with self.database.session() as session:
            if session.get(
                Device,
                device_id,
            ) is None:
                return OnvifEventIngestResult(
                    ignored=len(notifications),
                )

            for notification in notifications:
                normalized = (
                    normalize_onvif_notification(
                        notification
                    )
                )
                if normalized is None:
                    counters["ignored"] += 1
                    continue
                outcome, _event = (
                    self._ingest_one(
                        session,
                        device_id=device_id,
                        normalized=normalized,
                    )
                )
                counters[outcome] += 1
            session.commit()

        if any(
            counters[key]
            for key in (
                "created",
                "updated",
                "closed",
            )
        ):
            self.logger.debug(
                "ONVIF notifications ingested",
                extra={
                    "device_id": str(device_id),
                    **counters,
                },
            )

        return OnvifEventIngestResult(
            created=counters["created"],
            updated=counters["updated"],
            closed=counters["closed"],
            ignored=counters["ignored"],
        )
