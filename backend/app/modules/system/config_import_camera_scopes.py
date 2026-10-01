"""Apply imported role camera scopes after camera and group mapping."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.modules.auth.camera_scope import CameraScopeService

from .config_import_support import ConfigurationApplyItem


def apply_role_camera_scopes(
    service: type,
    session: Session,
    *,
    roles: list[dict[str, Any]],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    role_map: dict[str, uuid.UUID],
    camera_map: dict[str, uuid.UUID],
    group_map: dict[str, uuid.UUID],
) -> None:
    for raw in roles:
        assert isinstance(raw, dict)
        item = raw
        target_role = role_map.get(
            str(item["id"])
        )
        scope = item.get(
            "camera_scope"
        )
        if (
            target_role is None
            or scope is None
        ):
            continue
        assert isinstance(scope, dict)
        mode = str(scope["mode"])
        target_cameras: list[
            uuid.UUID
        ] = []
        target_groups: list[
            uuid.UUID
        ] = []
        missing = False
        for source_id in scope.get(
            "camera_ids",
            [],
        ):
            mapped = camera_map.get(
                str(source_id)
            )
            if mapped is None:
                missing = True
                break
            target_cameras.append(mapped)
        if not missing:
            for source_id in scope.get(
                "camera_group_ids",
                [],
            ):
                mapped = group_map.get(
                    str(source_id)
                )
                if mapped is None:
                    missing = True
                    break
                target_groups.append(mapped)
        if missing:
            skipped.append(
                service._apply_item(
                    section="roles",
                    resource_type=(
                        "role_camera_scope"
                    ),
                    item=item,
                    action="skipped",
                    target_id=target_role,
                    reason=(
                        "camera_scope_dependency_unmapped"
                    ),
                )
            )
            continue
        CameraScopeService.set_scope(
            session,
            principal_type="role",
            principal_id=target_role,
            mode=mode,
            camera_ids=target_cameras,
            camera_group_ids=(
                target_groups
            ),
        )
        applied.append(
            service._apply_item(
                section="roles",
                resource_type=(
                    "role_camera_scope"
                ),
                item=item,
                action="updated",
                target_id=target_role,
            )
        )
