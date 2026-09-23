from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class OnvifNormalizedNotification:
    topic: str
    occurred_at: datetime
    property_operation: str | None
    source_items: dict[str, str]
    data_items: dict[str, str]
    state: bool | None
    category: str
    label: str
    source_event_id: str


def _read(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    nested = (
        _read(value, "_value_1")
        or _read(value, "value")
        or _read(value, "Value")
    )
    if nested is not None and nested is not value:
        return _text(nested)
    rendered = str(value).strip()
    return rendered or None


def _items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def _simple_items(container: Any) -> dict[str, str]:
    raw = _read(container, "SimpleItem")
    result: dict[str, str] = {}
    for item in _items(raw):
        name = _text(
            _read(item, "Name")
            or _read(item, "name")
        )
        value = _text(
            _read(item, "Value")
            or _read(item, "value")
        )
        if name and value is not None:
            result[name] = value[:1024]
    return result


def _message(notification: Any) -> Any:
    current = _read(notification, "Message")
    for _ in range(3):
        nested = _read(current, "Message")
        if nested is None or nested is current:
            break
        current = nested
    return current


def _instant(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    text = _text(value)
    if text:
        try:
            parsed = datetime.fromisoformat(
                text.replace("Z", "+00:00")
            )
            if (
                parsed.tzinfo is None
                or parsed.utcoffset() is None
            ):
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _state(data_items: dict[str, str]) -> bool | None:
    preferred = (
        "ismotion",
        "state",
        "logicalstate",
        "objectisinside",
        "isinside",
        "active",
    )
    lookup = {
        key.casefold(): value
        for key, value in data_items.items()
    }
    for key in preferred:
        raw = lookup.get(key)
        if raw is None:
            continue
        normalized = raw.strip().casefold()
        if normalized in {
            "true",
            "1",
            "on",
            "active",
            "yes",
        }:
            return True
        if normalized in {
            "false",
            "0",
            "off",
            "inactive",
            "no",
        }:
            return False
    return None


def _topic_parts(topic: str) -> list[str]:
    return [
        part
        for part in re.split(r"[/.:]+", topic)
        if part
    ]


def _category_label(topic: str) -> tuple[str, str]:
    folded = topic.casefold()
    if "motion" in folded:
        return "motion", "motion"
    if "tamper" in folded:
        return "tamper", "tamper"
    if "line" in folded and "cross" in folded:
        return "analytics", "line_crossing"
    if "intrusion" in folded:
        return "analytics", "intrusion"
    if "digitalinput" in folded or "input" in folded:
        return "digital_input", "digital_input"
    if "audio" in folded or "sound" in folded:
        return "audio", "audio"

    parts = _topic_parts(topic)
    leaf = parts[-1] if parts else "event"
    label = re.sub(
        r"(?<!^)(?=[A-Z])",
        "_",
        leaf,
    ).replace("-", "_").casefold()
    return "device_event", label[:128]


def _fingerprint(
    *,
    topic: str,
    occurred_at: datetime,
    property_operation: str | None,
    source_items: dict[str, str],
    data_items: dict[str, str],
) -> str:
    pieces = [
        topic,
        occurred_at.isoformat(),
        property_operation or "",
    ]
    pieces.extend(
        f"s:{key}={value}"
        for key, value in sorted(source_items.items())
    )
    pieces.extend(
        f"d:{key}={value}"
        for key, value in sorted(data_items.items())
    )
    digest = hashlib.sha256(
        "\n".join(pieces).encode("utf-8")
    ).hexdigest()
    return f"notification:{digest[:48]}"


def normalize_onvif_notification(
    notification: Any,
) -> OnvifNormalizedNotification | None:
    topic = _text(_read(notification, "Topic"))
    message = _message(notification)
    if topic is None or message is None:
        return None

    occurred_at = _instant(
        _read(message, "UtcTime")
        or _read(message, "utc_time")
    )
    property_operation = _text(
        _read(message, "PropertyOperation")
        or _read(message, "property_operation")
    )
    source_items = _simple_items(
        _read(message, "Source")
    )
    data_items = _simple_items(
        _read(message, "Data")
    )
    category, label = _category_label(topic)

    return OnvifNormalizedNotification(
        topic=topic[:512],
        occurred_at=occurred_at,
        property_operation=(
            property_operation[:64]
            if property_operation
            else None
        ),
        source_items=source_items,
        data_items=data_items,
        state=_state(data_items),
        category=category,
        label=label,
        source_event_id=_fingerprint(
            topic=topic,
            occurred_at=occurred_at,
            property_operation=property_operation,
            source_items=source_items,
            data_items=data_items,
        ),
    )
