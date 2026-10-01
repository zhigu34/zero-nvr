"""Apply backup policies only where local repository credentials exist."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.backups.models import BackupPolicy
from app.modules.backups.service import BackupPolicyService

from .config_import_support import ConfigurationApplyItem


def apply_backup_policies(
    service: type,
    session: Session,
    *,
    settings: Settings,
    sections: dict[str, Any],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
) -> None:
    backup_items = sections.get(
        "backup_policies",
        [],
    )
    assert isinstance(backup_items, list)
    backup_service = (
        BackupPolicyService(settings)
    )
    for raw in backup_items:
        assert isinstance(raw, dict)
        item = raw
        source_uuid = service._source_uuid(
            item
        )
        target = session.get(
            BackupPolicy,
            source_uuid,
        )
        if target is None:
            target = (
                service._existing_by_name(
                    session,
                    BackupPolicy,
                    str(item["name"]),
                )
            )
        if target is None:
            skipped.append(
                service._apply_item(
                    section="backup_policies",
                    resource_type=(
                        "backup_policy"
                    ),
                    item=item,
                    action="skipped",
                    reason=(
                        "credential_required"
                    ),
                )
            )
            continue
        if (
            target.database_backend
            != str(
                item[
                    "database_backend"
                ]
            )
        ):
            skipped.append(
                service._apply_item(
                    section="backup_policies",
                    resource_type=(
                        "backup_policy"
                    ),
                    item=item,
                    action="skipped",
                    target_id=target.id,
                    reason=(
                        "database_backend_mismatch"
                    ),
                )
            )
            continue
        target = backup_service.update(
            session,
            policy=target,
            changes={
                "enabled": bool(
                    item["enabled"]
                ),
                "schedule": dict(
                    item.get(
                        "schedule"
                    )
                    or {}
                ),
                "retention": dict(
                    item.get(
                        "retention"
                    )
                    or {}
                ),
                "verify_after_backup": bool(
                    item[
                        "verify_after_backup"
                    ]
                ),
                "repository_check_schedule": dict(
                    item.get(
                        "repository_check_schedule"
                    )
                    or {}
                ),
                "include_deployment_config": bool(
                    item[
                        "include_deployment_config"
                    ]
                ),
            },
        )
        applied.append(
            service._apply_item(
                section="backup_policies",
                resource_type=(
                    "backup_policy"
                ),
                item=item,
                action="updated",
                target_id=target.id,
            )
        )
