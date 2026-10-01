from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.db.repository import fetch_or_404
from app.core.errors import ApiError
from app.core.pagination import Page, normalize_page_limit, paginate
from app.modules.storage.models import RecordingLocation

from .models import RecordingSegment


class RecordingCatalogQueryService:
    @staticmethod
    def get_segment(
        session: Session,
        segment_id: uuid.UUID,
    ) -> RecordingSegment:
        segment = fetch_or_404(
            session,
            RecordingSegment,
            segment_id,
            code="recording_not_found",
            message="Recording segment was not found.",
        )
        return segment

    @staticmethod
    def locations(
        session: Session,
        *,
        segment_id: uuid.UUID,
    ) -> list[RecordingLocation]:
        return list(
            session.scalars(
                select(RecordingLocation)
                .options(
                    joinedload(RecordingLocation.storage_target)
                )
                .where(
                    RecordingLocation.recording_segment_id
                    == segment_id
                )
                .order_by(
                    RecordingLocation.created_at,
                    RecordingLocation.id,
                )
            )
        )

    @staticmethod
    def list_camera(
        session: Session,
        *,
        camera_id: uuid.UUID,
        start_at: datetime | None,
        end_at: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> Page[RecordingSegment]:
        normalize_page_limit(
            limit,
            error_code="recording_limit_invalid",
            resource_label="Recording",
        )
        if (
            start_at is not None
            and end_at is not None
            and end_at <= start_at
        ):
            raise ApiError(
                status_code=400,
                code="invalid_time_range",
                message="Recording range end must be after range start.",
            )

        statement = select(RecordingSegment).where(
            RecordingSegment.camera_id == camera_id
        )

        if start_at is not None:
            statement = statement.where(
                RecordingSegment.ended_at > start_at
            )
        if end_at is not None:
            statement = statement.where(
                RecordingSegment.started_at < end_at
            )

        return paginate(
            session,
            statement,
            timestamp_column=RecordingSegment.started_at,
            id_column=RecordingSegment.id,
            cursor=cursor,
            limit=limit,
            cursor_key="started_at",
            cursor_error_code="recording_cursor_invalid",
            resource_label="Recording",
        )
