from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.integrations.frigate.normalizer import FrigateEventNormalizer
from app.modules.events.models import Event
from app.modules.events.service import EventService
from app.modules.recordings.models import RecordingTrigger
from app.modules.recordings.triggers import RecordingTriggerService
from app.modules.system.frigate import FrigateProviderConfig


@dataclass(frozen=True, slots=True)
class FrigateIngestResult:
    event: Event | None
    created: bool = False
    ignored: bool = False
    ignore_reason: str | None = None
    trigger: RecordingTrigger | None = None
    trigger_changed: bool = False
    trigger_camera_id: uuid.UUID | None = None


class FrigateEventIngestService:
    @staticmethod
    def _persist(
        session: Session,
        *,
        config: FrigateProviderConfig,
        normalized,
    ) -> FrigateIngestResult:
        if normalized.item is None:
            return FrigateIngestResult(
                event=None,
                ignored=normalized.ignored,
                ignore_reason=normalized.ignore_reason,
            )

        event_result = EventService.upsert_provider_event(
            session,
            item=normalized.item,
        )
        event = event_result.event

        trigger: RecordingTrigger | None = None
        trigger_changed = False
        if (
            event.camera_id is not None
            and event.source_event_id is not None
            and event.source_instance_id is not None
        ):
            zones = event.metadata_json.get("zones", [])
            normalized_zones = [
                str(item)
                for item in zones
                if isinstance(item, str)
            ] if isinstance(zones, list) else []

            trigger, trigger_changed = (
                RecordingTriggerService.upsert_provider(
                    session,
                    camera_id=event.camera_id,
                    source="frigate",
                    source_instance_id=event.source_instance_id,
                    source_event_id=event.source_event_id,
                    event_started_at=event.started_at,
                    event_ended_at=event.ended_at,
                    trigger_type="AI_OBJECT",
                    reason=event.label,
                    label=event.label,
                    confidence=event.confidence,
                    zones=normalized_zones,
                    metadata={
                        "event_id": str(event.id),
                        "label": event.label,
                        "zones": normalized_zones,
                    },
                )
            )

        return FrigateIngestResult(
            event=event,
            created=event_result.created,
            trigger=trigger,
            trigger_changed=trigger_changed,
            trigger_camera_id=(
                trigger.camera_id
                if trigger is not None
                else None
            ),
        )

    @classmethod
    def mqtt(
        cls,
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
        return cls._persist(
            session,
            config=config,
            normalized=normalized,
        )

    @classmethod
    def http(
        cls,
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
        return cls._persist(
            session,
            config=config,
            normalized=normalized,
        )
