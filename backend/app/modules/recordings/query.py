from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ApiError
from app.modules.storage.models import RecordingLocation

from .models import RecordingSegment


@dataclass(frozen=True, slots=True)
class RecordingCatalogPage:
    items: list[RecordingSegment]
    next_cursor: str | None


def _encode_cursor(segment: RecordingSegment) -> str:
    payload = json.dumps(
        {
            "started_at": segment.started_at.astimezone(UTC).isoformat(),
            "id": str(segment.id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(
                value + padding
            ).decode("utf-8")
        )
        started_at = datetime.fromisoformat(payload["started_at"])
        if (
            started_at.tzinfo is None
            or started_at.utcoffset() is None
        ):
            raise ValueError
        return (
            started_at.astimezone(UTC),
            uuid.UUID(payload["id"]),
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ApiError(
            status_code=400,
            code="recording_cursor_invalid",
            message="Recording cursor is invalid.",
        ) from exc


class RecordingCatalogQueryService:
    @staticmethod
    def get_segment(
        session: Session,
        segment_id: uuid.UUID,
    ) -> RecordingSegment:
        segment = session.get(RecordingSegment, segment_id)
        if segment is None:
            raise ApiError(
                status_code=404,
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
    ) -> RecordingCatalogPage:
        if limit < 1 or limit > 200:
            raise ApiError(
                status_code=400,
                code="recording_limit_invalid",
                message="Recording limit must be between 1 and 200.",
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

        if cursor is not None:
            cursor_started, cursor_id = _decode_cursor(cursor)
            statement = statement.where(
                or_(
                    RecordingSegment.started_at < cursor_started,
                    and_(
                        RecordingSegment.started_at == cursor_started,
                        RecordingSegment.id < cursor_id,
                    ),
                )
            )

        rows = list(
            session.scalars(
                statement.order_by(
                    RecordingSegment.started_at.desc(),
                    RecordingSegment.id.desc(),
                ).limit(limit + 1)
            )
        )

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = (
            _encode_cursor(items[-1])
            if has_more and items
            else None
        )
        return RecordingCatalogPage(
            items=items,
            next_cursor=next_cursor,
        )
