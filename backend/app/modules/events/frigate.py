from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.integrations.frigate import FrigateEventNormalizer
from app.modules.events.models import Event
from app.modules.events.service import EventService

from app.modules.system.frigate import FrigateProviderConfig


@dataclass(frozen=True, slots=True)
class FrigateIngestResult:
    event: Event | None
    created: bool = False
    ignored: bool = False
    ignore_reason: str | None = None


class FrigateEventIngestService:
    @staticmethod
    def mqtt(
        session: Session,
        *,
        config: FrigateProviderConfig,
        payload: Mapping[str, Any],
    ) -> FrigateIngestResult:
        normalized = FrigateEventNormalizer.mqtt_event(
            instance_id=config.instance_id,
            camera_map=config.camera_map,
            payload=payload,
        )
        if normalized.item is None:
            return FrigateIngestResult(
                event=None,
                ignored=normalized.ignored,
                ignore_reason=normalized.ignore_reason,
            )

        result = EventService.upsert_provider_event(
            session,
            item=normalized.item,
        )
        return FrigateIngestResult(
            event=result.event,
            created=result.created,
        )

    @staticmethod
    def http(
        session: Session,
        *,
        config: FrigateProviderConfig,
        payload: Mapping[str, Any],
    ) -> FrigateIngestResult:
        normalized = FrigateEventNormalizer.http_event(
            instance_id=config.instance_id,
            camera_map=config.camera_map,
            payload=payload,
        )
        if normalized.item is None:
            return FrigateIngestResult(
                event=None,
                ignored=normalized.ignored,
                ignore_reason=normalized.ignore_reason,
            )

        result = EventService.upsert_provider_event(
            session,
            item=normalized.item,
        )
        return FrigateIngestResult(
            event=result.event,
            created=result.created,
        )
