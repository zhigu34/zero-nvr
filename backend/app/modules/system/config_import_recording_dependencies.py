"""Map imported recording-policy references to local resource IDs."""

from __future__ import annotations

from typing import Any
import uuid


def map_recording_dependencies(
    item: dict[str, Any],
    *,
    camera_map: dict[str, uuid.UUID],
    storage_map: dict[str, uuid.UUID],
    retention_map: dict[str, uuid.UUID],
) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None] | str:
    """Return mapped IDs, or the first dependency that cannot be mapped."""
    target_camera = camera_map.get(str(item["camera_id"]))
    if target_camera is None:
        return "camera_unmapped"

    source_storage = item.get("storage_target_id")
    target_storage = (
        storage_map.get(str(source_storage))
        if source_storage is not None
        else None
    )
    if source_storage is not None and target_storage is None:
        return "storage_target_unmapped"

    source_retention = item.get("retention_policy_id")
    target_retention = (
        retention_map.get(str(source_retention))
        if source_retention is not None
        else None
    )
    if source_retention is not None and target_retention is None:
        return "retention_policy_unmapped"

    return target_camera, target_storage, target_retention
