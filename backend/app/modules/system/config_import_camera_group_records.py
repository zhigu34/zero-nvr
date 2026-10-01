"""Create or update one mapped camera group and its local membership."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.modules.cameras.groups import CameraGroupService
from app.modules.cameras.models import CameraGroup


def upsert_camera_group(
    service: type,
    session: Session,
    *,
    item: dict[str, Any],
    target_parent: uuid.UUID | None,
    target_cameras: list[uuid.UUID],
) -> tuple[CameraGroup, str]:
    source_uuid = service._source_uuid(
        item
    )
    target = session.get(
        CameraGroup,
        source_uuid,
    )
    if target is None:
        target = (
            service._existing_by_name(
                session,
                CameraGroup,
                str(item["name"]),
            )
        )
    description = item.get(
        "description"
    )
    if target is None:
        target = (
            CameraGroupService.create(
                session,
                name=str(
                    item["name"]
                ),
                description=(
                    str(description)
                    if description
                    is not None
                    else None
                ),
                parent_id=(
                    target_parent
                ),
                camera_ids=(
                    target_cameras
                ),
            )
        )
        action = "created"
    else:
        target = (
            CameraGroupService.update(
                session,
                group=target,
                changes={
                    "name": str(
                        item["name"]
                    ),
                    "description": (
                        str(description)
                        if description
                        is not None
                        else None
                    ),
                    "parent_id": (
                        target_parent
                    ),
                    "camera_ids": (
                        target_cameras
                    ),
                },
            )
        )
        action = "updated"
    return target, action
