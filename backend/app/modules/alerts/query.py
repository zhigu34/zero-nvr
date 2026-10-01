from __future__ import annotations

import uuid

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session

from app.core.db.repository import fetch_or_404
from app.core.errors import ApiError
from app.core.pagination import Page, normalize_page_limit, paginate

from .models import Alert


class AlertQueryService:
    @staticmethod
    def get(
        session: Session,
        alert_id: uuid.UUID,
    ) -> Alert:
        alert = fetch_or_404(
            session,
            Alert,
            alert_id,
            code="alert_not_found",
            message="Alert was not found.",
        )
        return alert

    @staticmethod
    def list(
        session: Session,
        *,
        allowed_camera_ids: frozenset[uuid.UUID] | None,
        include_system_alerts: bool,
        camera_id: uuid.UUID | None,
        state: str | None,
        severity: str | None,
        cursor: str | None,
        limit: int,
    ) -> Page[Alert]:
        normalize_page_limit(
            limit,
            error_code="alert_limit_invalid",
            resource_label="Alert",
        )

        statement = select(Alert)
        if camera_id is not None:
            statement = statement.where(
                Alert.camera_id == camera_id
            )
        elif allowed_camera_ids is None:
            if not include_system_alerts:
                statement = statement.where(
                    Alert.camera_id.is_not(None)
                )
        else:
            visible = []
            if allowed_camera_ids:
                visible.append(
                    Alert.camera_id.in_(
                        allowed_camera_ids
                    )
                )
            if include_system_alerts:
                visible.append(
                    Alert.camera_id.is_(None)
                )
            statement = statement.where(
                or_(*visible)
                if visible
                else false()
            )

        if state:
            if state not in {
                "OPEN",
                "ACKNOWLEDGED",
                "RESOLVED",
            }:
                raise ApiError(
                    status_code=400,
                    code="alert_state_invalid",
                    message="Alert state is invalid.",
                )
            statement = statement.where(
                Alert.state == state
            )

        if severity:
            statement = statement.where(
                Alert.severity == severity
            )

        return paginate(
            session,
            statement,
            timestamp_column=Alert.created_at,
            id_column=Alert.id,
            cursor=cursor,
            limit=limit,
            cursor_key="created_at",
            cursor_error_code="alert_cursor_invalid",
            resource_label="Alert",
        )
