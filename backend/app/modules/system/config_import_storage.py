"""Apply storage targets and map export IDs to local targets."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.storage.models import StorageTarget
from app.modules.storage.service import StorageTargetService

from .config_import_support import ConfigurationApplyItem


def apply_storage_targets(
    service: type,
    session: Session,
    *,
    settings: Settings,
    sections: dict[str, Any],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    storage_map: dict[str, uuid.UUID],
) -> None:
    storage_service = (
        StorageTargetService(settings)
    )
    storage_targets = sections.get(
        "storage_targets",
        [],
    )
    assert isinstance(
        storage_targets,
        list,
    )
    for raw in storage_targets:
        assert isinstance(raw, dict)
        item = raw
        source_uuid = service._source_uuid(
            item
        )
        target = session.get(
            StorageTarget,
            source_uuid,
        )
        if target is None:
            target = service._existing_by_name(
                session,
                StorageTarget,
                str(item["name"]),
            )

        source_type = str(
            item["type"]
        )
        source_role = str(
            item["role"]
        )
        config = dict(
            item.get("config")
            or {}
        )
        if target is not None and (
            target.type != source_type
            or target.role != source_role
        ):
            skipped.append(
                service._apply_item(
                    section="storage_targets",
                    resource_type=(
                        "storage_target"
                    ),
                    item=item,
                    action="skipped",
                    target_id=target.id,
                    reason=(
                        "storage_target_type_conflict"
                    ),
                )
            )
            continue

        if source_type == "rclone":
            if (
                target is None
                or target.credential_secret_ref
                is None
            ):
                skipped.append(
                    service._apply_item(
                        section="storage_targets",
                        resource_type=(
                            "storage_target"
                        ),
                        item=item,
                        action="skipped",
                        target_id=(
                            target.id
                            if target
                            is not None
                            else None
                        ),
                        reason=(
                            "credential_required"
                        ),
                    )
                )
                continue
            target = storage_service.update(
                session,
                target=target,
                changes={
                    "enabled": bool(
                        item["enabled"]
                    ),
                    "config": config,
                },
            )
            action = "updated"
        elif target is None:
            target = storage_service.create(
                session,
                target_type=source_type,
                role=source_role,
                name=str(item["name"]),
                enabled=bool(
                    item["enabled"]
                ),
                config=config,
                rclone_config=None,
            )
            action = "created"
        else:
            target = storage_service.update(
                session,
                target=target,
                changes={
                    "enabled": bool(
                        item["enabled"]
                    ),
                    "config": config,
                },
            )
            action = "updated"

        storage_map[
            str(source_uuid)
        ] = target.id
        applied.append(
            service._apply_item(
                section="storage_targets",
                resource_type=(
                    "storage_target"
                ),
                item=item,
                action=action,
                target_id=target.id,
            )
        )
