"""Apply role resources and map exporter IDs to local role IDs."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.modules.auth.admin_service import AuthAdminService
from app.modules.auth.models import Role

from .config_import_support import ConfigurationApplyItem


def apply_roles(
    service: type,
    session: Session,
    *,
    sections: dict[str, Any],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    role_map: dict[str, uuid.UUID],
) -> list[dict[str, Any]]:
    roles = sections.get("roles", [])
    assert isinstance(roles, list)
    for raw in roles:
        assert isinstance(raw, dict)
        item = raw
        source_id = str(item["id"])
        name = str(item["name"])
        source_builtin = bool(
            item.get("built_in", False)
        )
        target = service._existing_by_name(
            session,
            Role,
            name,
        )

        if source_builtin:
            if (
                target is None
                or not target.built_in
            ):
                skipped.append(
                    service._apply_item(
                        section="roles",
                        resource_type="role",
                        item=item,
                        action="skipped",
                        reason=(
                            "builtin_role_unavailable"
                        ),
                    )
                )
                continue
            role_map[source_id] = target.id
            applied.append(
                service._apply_item(
                    section="roles",
                    resource_type="role",
                    item=item,
                    action="matched",
                    target_id=target.id,
                )
            )
            continue

        permissions = item.get(
            "permissions",
            [],
        )
        if not isinstance(
            permissions,
            list,
        ):
            raise service._error(
                "configuration_import_invalid",
                "Role permissions must be a list.",
            )
        description = item.get(
            "description"
        )
        description_text = (
            str(description)
            if description is not None
            else None
        )

        if target is None:
            target = (
                AuthAdminService.create_role(
                    session,
                    name=name,
                    description=(
                        description_text
                    ),
                    permissions=[
                        str(value)
                        for value in permissions
                    ],
                )
            )
            action = "created"
        elif target.built_in:
            skipped.append(
                service._apply_item(
                    section="roles",
                    resource_type="role",
                    item=item,
                    action="skipped",
                    target_id=target.id,
                    reason="role_name_conflict",
                )
            )
            continue
        else:
            target = (
                AuthAdminService.update_role(
                    session,
                    role=target,
                    changes={
                        "description": (
                            description_text
                        ),
                        "permissions": [
                            str(value)
                            for value
                            in permissions
                        ],
                    },
                )
            )
            action = "updated"

        role_map[source_id] = target.id
        applied.append(
            service._apply_item(
                section="roles",
                resource_type="role",
                item=item,
                action=action,
                target_id=target.id,
            )
        )
    return roles
