"""Apply notification targets while preserving local secret material."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.notifications.models import NotificationTarget
from app.modules.notifications.service import NotificationTargetService

from .config_import_support import ConfigurationApplyItem


def apply_notification_targets(
    service: type,
    session: Session,
    *,
    settings: Settings,
    sections: dict[str, Any],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    notification_map: dict[str, uuid.UUID],
) -> None:
    notification_service = (
        NotificationTargetService(
            settings
        )
    )
    notification_items = (
        sections.get(
            "notification_targets",
            [],
        )
    )
    assert isinstance(
        notification_items,
        list,
    )
    for raw in notification_items:
        assert isinstance(raw, dict)
        item = raw
        source_uuid = service._source_uuid(
            item
        )
        target = session.get(
            NotificationTarget,
            source_uuid,
        )
        if target is None:
            target = (
                service._existing_by_name(
                    session,
                    NotificationTarget,
                    str(item["name"]),
                )
            )
        credential_required = bool(
            item.get("url_configured")
            or item.get(
                "credentials_configured"
            )
        )
        if (
            target is None
            or (
                credential_required
                and target.secret_ref is None
            )
        ):
            skipped.append(
                service._apply_item(
                    section=(
                        "notification_targets"
                    ),
                    resource_type=(
                        "notification_target"
                    ),
                    item=item,
                    action="skipped",
                    target_id=(
                        target.id
                        if target is not None
                        else None
                    ),
                    reason=(
                        "credential_required"
                    ),
                )
            )
            continue

        changes = {
            "enabled": bool(
                item["enabled"]
            ),
            "config": dict(
                item.get(
                    "config"
                )
                or {}
            ),
        }
        if target.kind == "smtp":
            target = (
                notification_service.update_smtp(
                    session,
                    target=target,
                    changes=changes,
                )
            )
        else:
            target = (
                notification_service.update(
                    session,
                    target=target,
                    changes=changes,
                )
            )
        notification_map[
            str(source_uuid)
        ] = target.id
        applied.append(
            service._apply_item(
                section=(
                    "notification_targets"
                ),
                resource_type=(
                    "notification_target"
                ),
                item=item,
                action="updated",
                target_id=target.id,
            )
        )
