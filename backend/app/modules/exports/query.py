from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.pagination import Page, normalize_page_limit, paginate

from .models import ExportJob


class ExportQueryService:
    @staticmethod
    def list(
        session: Session,
        *,
        allowed_camera_ids: frozenset[uuid.UUID] | None,
        state: str | None,
        cursor: str | None,
        limit: int,
    ) -> Page[ExportJob]:
        normalize_page_limit(
            limit,
            error_code="export_limit_invalid",
            resource_label="Export",
        )

        statement = select(ExportJob)
        if allowed_camera_ids is not None:
            if not allowed_camera_ids:
                # No camera in scope, so nothing can be visible. Returning an
                # empty page avoids exposing whether any export exists.
                return Page(items=[], next_cursor=None)
            statement = statement.where(
                ExportJob.camera_id.in_(allowed_camera_ids)
            )
        if state is not None:
            allowed_states = {
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "EXPIRED",
            }
            if state not in allowed_states:
                raise ApiError(
                    status_code=400,
                    code="export_state_invalid",
                    message="Export state is invalid.",
                )
            statement = statement.where(
                ExportJob.state == state
            )

        return paginate(
            session,
            statement,
            timestamp_column=ExportJob.created_at,
            id_column=ExportJob.id,
            cursor=cursor,
            limit=limit,
            cursor_key="created_at",
            cursor_error_code="export_cursor_invalid",
            resource_label="Export",
        )
