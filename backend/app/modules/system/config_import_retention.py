"""Apply retention policies before recording policies consume their ID map."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from .config_import_retention_records import upsert_retention_policy
from .config_import_support import ConfigurationApplyItem


def apply_retention_policies(
    service: type,
    session: Session,
    *,
    retention: dict[str, Any],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    camera_map: dict[str, uuid.UUID],
    group_map: dict[str, uuid.UUID],
    retention_map: dict[str, uuid.UUID],
) -> None:
    retention_items = retention.get(
        "retention_policies",
        [],
    )
    assert isinstance(
        retention_items,
        list,
    )
    for raw in retention_items:
        assert isinstance(raw, dict)
        item = raw
        source_uuid = service._source_uuid(
            item
        )
        scope_type = str(
            item["scope_type"]
        )
        source_scope = item.get(
            "scope_id"
        )
        target_scope: uuid.UUID | None = None
        if scope_type == "CAMERA":
            target_scope = (
                camera_map.get(
                    str(source_scope)
                )
            )
        elif (
            scope_type
            == "CAMERA_GROUP"
        ):
            target_scope = (
                group_map.get(
                    str(source_scope)
                )
            )
        if (
            scope_type != "GLOBAL"
            and target_scope is None
        ):
            skipped.append(
                service._apply_item(
                    section="recording",
                    resource_type=(
                        "retention_policy"
                    ),
                    item=item,
                    action="skipped",
                    reason=(
                        "scope_dependency_unmapped"
                    ),
                )
            )
            continue

        target, action = upsert_retention_policy(
            service, session, item=item, source_uuid=source_uuid,
            scope_type=scope_type, target_scope=target_scope,
        )
        retention_map[
            str(source_uuid)
        ] = target.id
        applied.append(
            service._apply_item(
                section="recording",
                resource_type=(
                    "retention_policy"
                ),
                item=item,
                action=action,
                target_id=target.id,
            )
        )
