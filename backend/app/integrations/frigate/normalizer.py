from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from app.core.errors import ApiError
from app.modules.events.service import EventIngest


@dataclass(frozen=True, slots=True)
class FrigateNormalizedEvent:
    item: EventIngest | None
    ignored: bool = False
    ignore_reason: str | None = None


class FrigateEventNormalizer:
    """Normalize current Frigate MQTT/HTTP object events.

    Raw provider payloads are not persisted. Only stable product facts plus a
    bounded set of useful provider metadata enter canonical Event rows.
    """

    @staticmethod
    def _timestamp(
        value: object,
        *,
        field_name: str,
        required: bool = True,
    ) -> datetime | None:
        if value is None:
            if required:
                raise ApiError(
                    status_code=422,
                    code="frigate_event_invalid",
                    message=f"Frigate event {field_name} is required.",
                )
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (TypeError, ValueError, OSError) as exc:
            raise ApiError(
                status_code=422,
                code="frigate_event_invalid",
                message=f"Frigate event {field_name} is invalid.",
            ) from exc

    @staticmethod
    def _text(
        value: object,
        *,
        field_name: str,
        required: bool = False,
        max_length: int = 512,
    ) -> str | None:
        if value is None:
            if required:
                raise ApiError(
                    status_code=422,
                    code="frigate_event_invalid",
                    message=f"Frigate event {field_name} is required.",
                )
            return None
        text = str(value).strip()
        if not text:
            if required:
                raise ApiError(
                    status_code=422,
                    code="frigate_event_invalid",
                    message=f"Frigate event {field_name} is required.",
                )
            return None
        if len(text) > max_length:
            raise ApiError(
                status_code=422,
                code="frigate_event_invalid",
                message=f"Frigate event {field_name} is too long.",
            )
        return text

    @staticmethod
    def _confidence(value: object) -> float | None:
        if value is None:
            return None
        try:
            score = float(value)
        except (TypeError, ValueError) as exc:
            raise ApiError(
                status_code=422,
                code="frigate_event_invalid",
                message="Frigate event confidence is invalid.",
            ) from exc
        if not 0 <= score <= 1:
            raise ApiError(
                status_code=422,
                code="frigate_event_invalid",
                message="Frigate event confidence is outside 0..1.",
            )
        return score

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            normalized = item.strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result[:64]

    @staticmethod
    def _sub_label(value: object) -> tuple[str | None, float | None]:
        if isinstance(value, str):
            text = value.strip()
            return (text or None, None)
        if isinstance(value, list) and value:
            name = (
                str(value[0]).strip()
                if value[0] is not None
                else ""
            )
            score: float | None = None
            if len(value) > 1 and value[1] is not None:
                try:
                    parsed = float(value[1])
                    if 0 <= parsed <= 1:
                        score = parsed
                except (TypeError, ValueError):
                    pass
            return (name or None, score)
        return (None, None)

    @classmethod
    def _normalize_object(
        cls,
        *,
        instance_id: str,
        camera_map: Mapping[str, uuid.UUID],
        data: Mapping[str, Any],
        message_type: str | None,
    ) -> FrigateNormalizedEvent:
        if bool(data.get("false_positive")):
            return FrigateNormalizedEvent(
                item=None,
                ignored=True,
                ignore_reason="false_positive",
            )

        event_id = cls._text(
            data.get("id"),
            field_name="id",
            required=True,
        )
        camera_key = cls._text(
            data.get("camera"),
            field_name="camera",
            required=True,
            max_length=256,
        )
        assert event_id is not None
        assert camera_key is not None

        camera_id = camera_map.get(camera_key)
        if camera_id is None:
            return FrigateNormalizedEvent(
                item=None,
                ignored=True,
                ignore_reason="camera_unmapped",
            )

        label = cls._text(
            data.get("label"),
            field_name="label",
            required=True,
            max_length=128,
        )
        started_at = cls._timestamp(
            data.get("start_time"),
            field_name="start_time",
        )
        ended_at = cls._timestamp(
            data.get("end_time"),
            field_name="end_time",
            required=False,
        )
        assert started_at is not None

        entered_zones = cls._string_list(
            data.get("entered_zones", data.get("zones"))
        )
        current_zones = cls._string_list(
            data.get("current_zones")
        )
        all_zones = sorted(
            set(entered_zones) | set(current_zones)
        )
        primary_zone = (
            entered_zones[0]
            if entered_zones
            else (
                current_zones[0]
                if current_zones
                else None
            )
        )

        sub_label, sub_label_score = cls._sub_label(
            data.get("sub_label")
        )
        metadata: dict[str, Any] = {
            "provider_message_type": message_type,
            "camera_key": camera_key,
            "zones": all_zones,
            "entered_zones": entered_zones,
            "current_zones": current_zones,
            "has_snapshot": bool(data.get("has_snapshot")),
            "has_clip": bool(data.get("has_clip")),
        }
        if sub_label is not None:
            metadata["sub_label"] = sub_label
        if sub_label_score is not None:
            metadata["sub_label_score"] = sub_label_score

        attributes = data.get("attributes")
        if isinstance(attributes, dict):
            metadata["attributes"] = {
                str(key): value
                for key, value in list(attributes.items())[:64]
                if isinstance(key, str)
                and isinstance(value, (str, int, float, bool, type(None)))
            }

        provider_data = data.get("data")
        if isinstance(provider_data, dict):
            for key in (
                "description",
                "average_estimated_speed",
                "velocity_angle",
                "recognized_license_plate",
                "recognized_license_plate_score",
            ):
                value = provider_data.get(key)
                if isinstance(
                    value,
                    (str, int, float, bool, type(None)),
                ):
                    metadata[key] = value

        for key in (
            "average_estimated_speed",
            "velocity_angle",
            "recognized_license_plate",
            "recognized_license_plate_score",
        ):
            value = data.get(key)
            if isinstance(
                value,
                (str, int, float, bool, type(None)),
            ):
                metadata[key] = value

        snapshot_ref = (
            f"frigate://{instance_id}/event/{event_id}/snapshot"
            if bool(data.get("has_snapshot"))
            else None
        )

        return FrigateNormalizedEvent(
            item=EventIngest(
                source="frigate",
                source_instance_id=instance_id,
                source_event_id=event_id,
                camera_id=camera_id,
                category="object",
                label=label,
                started_at=started_at,
                ended_at=ended_at,
                confidence=cls._confidence(
                    data.get(
                        "top_score",
                        (
                            provider_data.get("top_score")
                            if isinstance(provider_data, dict)
                            else None
                        ),
                    )
                ),
                zone=primary_zone,
                snapshot_ref=snapshot_ref,
                metadata=metadata,
            )
        )

    @classmethod
    def mqtt_event(
        cls,
        *,
        instance_id: str,
        camera_map: Mapping[str, uuid.UUID],
        payload: Mapping[str, Any],
    ) -> FrigateNormalizedEvent:
        message_type = cls._text(
            payload.get("type"),
            field_name="type",
            max_length=32,
        )
        after = payload.get("after")
        if not isinstance(after, Mapping):
            raise ApiError(
                status_code=422,
                code="frigate_event_invalid",
                message="Frigate MQTT event has no valid after object.",
            )
        return cls._normalize_object(
            instance_id=instance_id,
            camera_map=camera_map,
            data=after,
            message_type=message_type,
        )

    @classmethod
    def http_event(
        cls,
        *,
        instance_id: str,
        camera_map: Mapping[str, uuid.UUID],
        payload: Mapping[str, Any],
    ) -> FrigateNormalizedEvent:
        data = dict(payload)
        # HTTP uses zones rather than entered_zones.
        if "entered_zones" not in data:
            data["entered_zones"] = data.get("zones")
        return cls._normalize_object(
            instance_id=instance_id,
            camera_map=camera_map,
            data=data,
            message_type="backfill",
        )
