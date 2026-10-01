"""Apply alert policies after mapping camera and notification IDs."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session


from .config_import_support import ConfigurationApplyItem
from .config_import_alert_dependencies import map_alert_dependencies
from .config_import_alert_policy_records import upsert_alert_policy


def apply_alert_policies(
    service: type,
    session: Session,
    *,
    sections: dict[str, Any],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    camera_map: dict[str, uuid.UUID],
    notification_map: dict[str, uuid.UUID],
) -> None:
    alert_items = sections.get(
        "alert_policies",
        [],
    )
    assert isinstance(alert_items, list)
    for raw in alert_items:
        assert isinstance(raw, dict)
        item = raw
        match, actions, dependency_missing = map_alert_dependencies(
            item, camera_map=camera_map,
            notification_map=notification_map,
        )
        if dependency_missing:
            skipped.append(
                service._apply_item(
                    section="alert_policies",
                    resource_type=(
                        "alert_policy"
                    ),
                    item=item,
                    action="skipped",
                    reason=(
                        "alert_dependency_unmapped"
                    ),
                )
            )
            continue

        target, action = upsert_alert_policy(
            service, session, item=item, match=match, actions=actions,
        )
        applied.append(
            service._apply_item(
                section="alert_policies",
                resource_type=(
                    "alert_policy"
                ),
                item=item,
                action=action,
                target_id=target.id,
            )
        )
