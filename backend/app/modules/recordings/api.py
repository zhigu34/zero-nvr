from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.modules.auth.dependencies import require_camera_permission
from app.modules.auth.service import AuthContext
from app.modules.cameras.service import CameraService

from .schemas import PlaybackTimelineView
from .timeline import PlaybackTimelineService


router = APIRouter()


def _normalized_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError(
            status_code=422,
            code="timezone_required",
            message=f"{field_name} must include a timezone offset.",
        )
    return value.astimezone(UTC)


@router.get(
    "/cameras/{camera_id}/timeline",
    response_model=PlaybackTimelineView,
)
def camera_timeline(
    camera_id: uuid.UUID,
    from_at: datetime = Query(alias="from"),
    to_at: datetime = Query(alias="to"),
    _context: AuthContext = Depends(
        require_camera_permission("recording.view")
    ),
    session: Session = Depends(get_db_session),
) -> PlaybackTimelineView:
    start_at = _normalized_utc(from_at, field_name="from")
    end_at = _normalized_utc(to_at, field_name="to")

    if end_at <= start_at:
        raise ApiError(
            status_code=422,
            code="invalid_time_range",
            message="Timeline range end must be after range start.",
        )

    CameraService.get_camera(session, camera_id)

    return PlaybackTimelineService.build(
        session,
        camera_id=camera_id,
        start_at=start_at,
        end_at=end_at,
    )
