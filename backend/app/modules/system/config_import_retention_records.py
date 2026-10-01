"""Match and persist a retention policy after its scope dependency is mapped."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.recordings.models import RetentionPolicy
from app.modules.storage.retention_admin import RetentionPolicyAdminService


def upsert_retention_policy(
    service: type,
    session: Session,
    *,
    item: dict[str, Any],
    source_uuid: uuid.UUID,
    scope_type: str,
    target_scope: uuid.UUID | None,
) -> tuple[RetentionPolicy, str]:
    target = session.get(
        RetentionPolicy,
        source_uuid,
    )
    if target is None:
        target = (
            service._existing_by_name(
                session,
                RetentionPolicy,
                str(item["name"]),
            )
        )
    if target is None:
        statement = select(
            RetentionPolicy
        ).where(
            RetentionPolicy.scope_type
            == scope_type
        )
        if target_scope is None:
            statement = (
                statement.where(
                    RetentionPolicy.scope_id
                    .is_(None)
                )
            )
        else:
            statement = (
                statement.where(
                    RetentionPolicy.scope_id
                    == target_scope
                )
            )
        target = session.scalar(
            statement
        )

    values = {
        "name": str(
            item["name"]
        ),
        "scope_type": scope_type,
        "scope_id": target_scope,
        "ordinary_keep_days": int(
            item[
                "ordinary_keep_days"
            ]
        ),
        "event_keep_days": int(
            item["event_keep_days"]
        ),
        "manual_keep_days": int(
            item["manual_keep_days"]
        ),
        "mode": str(item["mode"]),
        "require_archive_before_delete": bool(
            item[
                "require_archive_before_delete"
            ]
        ),
        "enabled": bool(
            item["enabled"]
        ),
    }
    if target is None:
        target = (
            RetentionPolicyAdminService.create(
                session,
                **values,
            )
        )
        action = "created"
    else:
        target = (
            RetentionPolicyAdminService.update(
                session,
                policy=target,
                changes=values,
            )
        )
        action = "updated"
    return target, action
