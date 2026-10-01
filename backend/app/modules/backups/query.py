from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.pagination import Page, normalize_page_limit, paginate

from .models import BackupSet


class BackupQueryService:
    @staticmethod
    def list(
        session: Session,
        *,
        policy_id: uuid.UUID | None,
        state: str | None,
        cursor: str | None,
        limit: int,
    ) -> Page[BackupSet]:
        normalize_page_limit(
            limit,
            error_code="backup_limit_invalid",
            resource_label="Backup",
        )

        statement = select(BackupSet)
        if policy_id is not None:
            statement = statement.where(
                BackupSet.backup_policy_id == policy_id
            )
        if state is not None:
            if state not in {
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "FAILED",
            }:
                raise ApiError(
                    status_code=400,
                    code="backup_state_invalid",
                    message="Backup state is invalid.",
                )
            statement = statement.where(
                BackupSet.state == state
            )

        return paginate(
            session,
            statement,
            timestamp_column=BackupSet.started_at,
            id_column=BackupSet.id,
            cursor=cursor,
            limit=limit,
            cursor_key="started_at",
            cursor_error_code="backup_cursor_invalid",
            resource_label="Backup",
        )
