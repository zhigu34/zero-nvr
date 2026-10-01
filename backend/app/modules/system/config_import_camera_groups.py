"""Apply camera groups after camera IDs have been mapped."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
import uuid

from sqlalchemy.orm import Session


from .config_import_support import ConfigurationApplyItem
from .config_import_camera_group_records import upsert_camera_group


def apply_camera_groups(
    service: type,
    session: Session,
    *,
    groups: list[dict[str, Any]],
    members: list[dict[str, Any]],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    camera_map: dict[str, uuid.UUID],
    group_map: dict[str, uuid.UUID],
) -> None:
    member_map: dict[
        str,
        list[str],
    ] = defaultdict(list)
    for raw in members:
        assert isinstance(raw, dict)
        member_map[
            str(
                raw["camera_group_id"]
            )
        ].append(
            str(raw["camera_id"])
        )

    pending_groups = [
        raw
        for raw in groups
        if isinstance(raw, dict)
    ]
    progress = True
    while pending_groups and progress:
        progress = False
        remaining: list[
            dict[str, Any]
        ] = []
        for item in pending_groups:
            source_id = str(
                item["id"]
            )
            source_parent = item.get(
                "parent_id"
            )
            target_parent = None
            if source_parent is not None:
                target_parent = (
                    group_map.get(
                        str(
                            source_parent
                        )
                    )
                )
                if target_parent is None:
                    remaining.append(
                        item
                    )
                    continue

            target_cameras: list[
                uuid.UUID
            ] = []
            member_missing = False
            for source_camera in (
                member_map.get(
                    source_id,
                    [],
                )
            ):
                target_camera = (
                    camera_map.get(
                        source_camera
                    )
                )
                if target_camera is None:
                    member_missing = True
                    break
                target_cameras.append(
                    target_camera
                )
            if member_missing:
                remaining.append(item)
                continue

            target, action = upsert_camera_group(
                service, session, item=item,
                target_parent=target_parent,
                target_cameras=target_cameras,
            )
            group_map[
                source_id
            ] = target.id
            applied.append(
                service._apply_item(
                    section="cameras",
                    resource_type=(
                        "camera_group"
                    ),
                    item=item,
                    action=action,
                    target_id=target.id,
                )
            )
            progress = True
        pending_groups = remaining

    for item in pending_groups:
        skipped.append(
            service._apply_item(
                section="cameras",
                resource_type=(
                    "camera_group"
                ),
                item=item,
                action="skipped",
                reason=(
                    "camera_or_parent_unmapped"
                ),
            )
        )

