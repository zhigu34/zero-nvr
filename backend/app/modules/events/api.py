from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.modules.auth.dependencies import (
    get_effective_camera_scope,
    require_permission,
)
from app.modules.auth.service import AuthContext
from app.integrations.frigate import (
    FrigateHttpAdapter,
    FrigateIntegrationError,
)
from app.modules.system.frigate import FrigateProviderSettingsService
from app.modules.recordings.query import RecordingCatalogQueryService

from .models import Event
from .query import EventQueryService
from .schemas import (
    EventPage,
    EventRecordingSegmentLinkView,
    EventRecordingSegmentPage,
    EventView,
)


router = APIRouter()


def _normalized_utc(
    value: datetime | None,
    *,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError(
            status_code=422,
            code="timezone_required",
            message=f"{field_name} must include a timezone offset.",
        )
    return value.astimezone(UTC)


def _event_view(event: Event) -> EventView:
    return EventView(
        id=event.id,
        source=event.source,
        source_instance_id=event.source_instance_id,
        source_event_id=event.source_event_id,
        camera_id=event.camera_id,
        category=event.category,
        label=event.label,
        started_at=event.started_at,
        ended_at=event.ended_at,
        confidence=event.confidence,
        severity=event.severity,
        zone=event.zone,
        snapshot_ref=event.snapshot_ref,
        correlation_id=event.correlation_id,
        metadata=event.metadata_json or {},
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


@router.get("/events", response_model=EventPage)
def list_events(
    camera_id: uuid.UUID | None = None,
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    source: str | None = None,
    category: str | None = None,
    label: str | None = None,
    zone: str | None = None,
    min_confidence: float | None = Query(
        default=None,
        alias="confidence",
    ),
    severity: str | None = None,
    cursor: str | None = None,
    limit: int = 100,
    context: AuthContext = Depends(
        require_permission("event.view")
    ),
    session: Session = Depends(get_db_session),
) -> EventPage:
    scope = get_effective_camera_scope(context, session)
    if camera_id is not None and not scope.allows(camera_id):
        raise ApiError(
            status_code=404,
            code="camera_not_found",
            message="Camera was not found.",
        )

    page = EventQueryService.list(
        session,
        allowed_camera_ids=(
            None if scope.all_cameras else scope.camera_ids
        ),
        camera_id=camera_id,
        start_at=_normalized_utc(
            from_at,
            field_name="from",
        ),
        end_at=_normalized_utc(
            to_at,
            field_name="to",
        ),
        source=source,
        category=category,
        label=label,
        zone=zone,
        min_confidence=min_confidence,
        severity=severity,
        cursor=cursor,
        limit=limit,
    )
    return EventPage(
        items=[_event_view(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/events/{event_id}", response_model=EventView)
def get_event(
    event_id: uuid.UUID,
    context: AuthContext = Depends(
        require_permission("event.view")
    ),
    session: Session = Depends(get_db_session),
) -> EventView:
    event = EventQueryService.get(session, event_id)
    if event.camera_id is not None:
        scope = get_effective_camera_scope(context, session)
        if not scope.allows(event.camera_id):
            raise ApiError(
                status_code=404,
                code="event_not_found",
                message="Event was not found.",
            )
    return _event_view(event)


@router.get(
    "/events/{event_id}/recordings",
    response_model=EventRecordingSegmentPage,
)
def list_event_recordings(
    event_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = 100,
    context: AuthContext = Depends(
        require_permission("event.view")
    ),
    session: Session = Depends(get_db_session),
) -> EventRecordingSegmentPage:
    if "recording.view" not in context.permissions:
        raise ApiError(
            status_code=403,
            code="permission_denied",
            message=(
                "You do not have permission to view recordings."
            ),
            details={"permission": "recording.view"},
        )

    event = EventQueryService.get(session, event_id)
    if event.camera_id is not None:
        scope = get_effective_camera_scope(
            context,
            session,
        )
        if not scope.allows(event.camera_id):
            raise ApiError(
                status_code=404,
                code="event_not_found",
                message="Event was not found.",
            )

    range_start = event.started_at
    if event.ended_at is None:
        range_end = datetime.now(UTC)
    elif event.ended_at <= event.started_at:
        range_end = event.started_at + timedelta(
            microseconds=1
        )
    else:
        range_end = event.ended_at

    if event.camera_id is None:
        return EventRecordingSegmentPage(
            event_id=event.id,
            camera_id=None,
            range_start_at=range_start,
            range_end_at=range_end,
            items=[],
            next_cursor=None,
        )

    page = RecordingCatalogQueryService.list_camera(
        session,
        camera_id=event.camera_id,
        start_at=range_start,
        end_at=range_end,
        cursor=cursor,
        limit=limit,
    )
    return EventRecordingSegmentPage(
        event_id=event.id,
        camera_id=event.camera_id,
        range_start_at=range_start,
        range_end_at=range_end,
        items=[
            EventRecordingSegmentLinkView(
                recording_segment_id=item.id,
                playback_ref=item.id,
                segment_start_at=item.started_at,
                segment_end_at=item.ended_at,
                overlap_start_at=max(
                    item.started_at,
                    range_start,
                ),
                overlap_end_at=min(
                    item.ended_at,
                    range_end,
                ),
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/events/{event_id}/snapshot")
def event_snapshot(
    event_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("event.view")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    event = EventQueryService.get(session, event_id)
    if event.camera_id is not None:
        scope = get_effective_camera_scope(context, session)
        if not scope.allows(event.camera_id):
            raise ApiError(
                status_code=404,
                code="event_not_found",
                message="Event was not found.",
            )

    if (
        event.source != "frigate"
        or event.source_event_id is None
        or event.source_instance_id is None
        or not event.snapshot_ref
    ):
        raise ApiError(
            status_code=404,
            code="event_snapshot_not_found",
            message="Event snapshot is unavailable.",
        )

    provider = FrigateProviderSettingsService(
        request.app.state.settings
    ).get(session)
    if (
        provider is None
        or not provider.enabled
        or provider.instance_id != event.source_instance_id
    ):
        raise ApiError(
            status_code=404,
            code="event_snapshot_not_found",
            message="Event snapshot is unavailable.",
        )

    try:
        with FrigateHttpAdapter(
            base_url=provider.base_url,
            bearer_token=provider.credentials.http_bearer_token,
            username=provider.credentials.http_username,
            password=provider.credentials.http_password,
            timeout_seconds=10.0,
        ) as adapter:
            content, content_type = adapter.snapshot(
                event.source_event_id
            )
    except FrigateIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
        ) from exc

    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )
