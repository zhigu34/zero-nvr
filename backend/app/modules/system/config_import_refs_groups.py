"""Validate camera-group hierarchy, members, and role camera scopes."""

from __future__ import annotations

from .config_import_document import ParsedSections
from .config_import_reference_ids import ReferenceIds


def validate_group_references(service: type, parsed: ParsedSections, ids: ReferenceIds) -> None:
    groups = parsed.groups
    members = parsed.members
    roles = parsed.roles
    camera_ids = ids.camera_ids
    group_ids = ids.group_ids
    for index, item in enumerate(groups):
        parent = item.get("parent_id")
        if parent is None:
            continue
        resolved = service._require_ref(
            parent,
            group_ids,
            path=(
                "$.sections.cameras.groups"
                f"[{index}].parent_id"
            ),
        )
        if resolved == item.get("id"):
            raise service._error(
                "configuration_import_reference_invalid",
                "Camera group cannot be its own parent.",
                details={
                    "path": (
                        "$.sections.cameras.groups"
                        f"[{index}].parent_id"
                    )
                },
            )

    for index, item in enumerate(members):
        service._require_ref(
            item.get("camera_group_id"),
            group_ids,
            path=(
                "$.sections.cameras.group_members"
                f"[{index}].camera_group_id"
            ),
        )
        service._require_ref(
            item.get("camera_id"),
            camera_ids,
            path=(
                "$.sections.cameras.group_members"
                f"[{index}].camera_id"
            ),
        )

    for index, item in enumerate(roles):
        scope = item.get("camera_scope")
        if scope is None:
            continue
        scope = service._mapping(
            scope,
            path=(
                "$.sections.roles"
                f"[{index}].camera_scope"
            ),
        )
        for camera_index, camera_id in enumerate(
            scope.get(
                "camera_ids",
                [],
            )
        ):
            service._require_ref(
                camera_id,
                camera_ids,
                path=(
                    "$.sections.roles"
                    f"[{index}].camera_scope.camera_ids"
                    f"[{camera_index}]"
                ),
            )
        for group_index, group_id in enumerate(
            scope.get(
                "camera_group_ids",
                [],
            )
        ):
            service._require_ref(
                group_id,
                group_ids,
                path=(
                    "$.sections.roles"
                    f"[{index}].camera_scope.camera_group_ids"
                    f"[{group_index}]"
                ),
            )

