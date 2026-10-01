"""Resolve an imported camera against an existing local camera."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.cameras.models import Camera


def match_existing_camera(
    session: Session,
    *,
    item: dict[str, Any],
    source_uuid: uuid.UUID,
    device_map: dict[str, uuid.UUID],
) -> Camera | None:
    target = session.get(Camera, source_uuid)
    if target is not None:
        return target

    source_device = item.get("device_id")
    target_device = (
        device_map.get(str(source_device))
        if source_device is not None
        else None
    )
    if target_device is None:
        return None

    return session.scalar(
        select(Camera).where(
            Camera.device_id == target_device,
            Camera.channel_key == str(item["channel_key"]),
        )
    )
