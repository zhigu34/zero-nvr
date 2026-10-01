"""Apply exported camera metadata to a matched local camera."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.cameras.models import Camera
from app.modules.cameras.service import CameraService


def update_camera_metadata(
    session: Session,
    *,
    camera: Camera,
    item: dict[str, Any],
) -> tuple[bool, bool]:
    target = camera
    before_camera = (
        target.name,
        target.location,
        target.storage_label,
        target.maintenance,
        target.time_sync_mode,
        target.enabled,
    )
    enabled_changed = (
        "enabled" in item
        and bool(
            item["enabled"]
        )
        != target.enabled
    )
    camera_changes: dict[
        str,
        object,
    ] = {
        "name": str(
            item["name"]
        ),
        "location": (
            str(item["location"])
            if item.get(
                "location"
            )
            is not None
            else None
        ),
        "storage_label": (
            str(
                item["storage_label"]
            )
            if item.get(
                "storage_label"
            )
            is not None
            else None
        ),
    }
    if "maintenance" in item:
        camera_changes[
            "maintenance"
        ] = bool(
            item["maintenance"]
        )
    if (
        "time_sync_mode"
        in item
    ):
        camera_changes[
            "time_sync_mode"
        ] = item[
            "time_sync_mode"
        ]
    CameraService.update_camera(
        session,
        camera=target,
        changes=camera_changes,
    )
    if "enabled" in item:
        CameraService.set_enabled(
            session,
            camera=target,
            enabled=bool(
                item["enabled"]
            ),
        )
    after_camera = (
        target.name,
        target.location,
        target.storage_label,
        target.maintenance,
        target.time_sync_mode,
        target.enabled,
    )
    return before_camera != after_camera, enabled_changed
