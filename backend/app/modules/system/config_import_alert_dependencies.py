"""Map exported alert camera and notification IDs to local IDs."""

from __future__ import annotations

from typing import Any
import uuid


def map_alert_dependencies(
    item: dict[str, Any],
    *,
    camera_map: dict[str, uuid.UUID],
    notification_map: dict[str, uuid.UUID],
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    match = dict(
        item.get("match")
        or {}
    )
    actions = dict(
        item.get("action")
        or {}
    )
    dependency_missing = False

    source_cameras = match.get(
        "camera_ids"
    )
    if isinstance(
        source_cameras,
        list,
    ):
        mapped_camera_ids: list[
            str
        ] = []
        for source_id in (
            source_cameras
        ):
            mapped = camera_map.get(
                str(source_id)
            )
            if mapped is None:
                dependency_missing = (
                    True
                )
                break
            mapped_camera_ids.append(
                str(mapped)
            )
        match[
            "camera_ids"
        ] = mapped_camera_ids

    source_targets = actions.get(
        "notification_target_ids"
    )
    if (
        not dependency_missing
        and isinstance(
            source_targets,
            list,
        )
    ):
        mapped_target_ids: list[
            str
        ] = []
        for source_id in (
            source_targets
        ):
            mapped = (
                notification_map.get(
                    str(source_id)
                )
            )
            if mapped is None:
                dependency_missing = (
                    True
                )
                break
            mapped_target_ids.append(
                str(mapped)
            )
        actions[
            "notification_target_ids"
        ] = mapped_target_ids

    return match, actions, dependency_missing
