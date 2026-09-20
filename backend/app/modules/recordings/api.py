from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import require_camera_permission
from app.modules.auth.service import AuthContext
from app.modules.cameras.media_runtime import CameraMediaRuntimeService
from app.modules.cameras.service import CameraService
from app.modules.storage.recording_resolver import RecordingStorageResolver

from .models import RecordingPolicy
from .policy import RecordingPolicyService
from .runtime import RecordingRuntimeService
from .schemas import (
    PlaybackTimelineView,
    RecordingPolicyPut,
    RecordingPolicyView,
    RecordingRuntimeView,
)
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


def _policy_view(
    policy: RecordingPolicy,
    *,
    runtime: RecordingRuntimeView | None = None,
) -> RecordingPolicyView:
    return RecordingPolicyView(
        id=policy.id,
        camera_id=policy.camera_id,
        baseline_mode=policy.baseline_mode,
        schedule=policy.schedule_json or {},
        schedule_timezone=policy.schedule_timezone,
        event_recording_enabled=policy.event_recording_enabled,
        event_filter=policy.event_filter_json or {},
        segment_target_seconds=policy.segment_target_seconds,
        pre_roll_seconds=policy.pre_roll_seconds,
        post_roll_seconds=policy.post_roll_seconds,
        storage_target_id=policy.storage_target_id,
        retention_policy_id=policy.retention_policy_id,
        enabled=policy.enabled,
        runtime=runtime,
    )


def _audit_snapshot(
    policy: RecordingPolicy | None,
) -> dict[str, Any] | None:
    if policy is None:
        return None
    return {
        "baseline_mode": policy.baseline_mode,
        "schedule": policy.schedule_json or {},
        "schedule_timezone": policy.schedule_timezone,
        "event_recording_enabled": policy.event_recording_enabled,
        "event_filter": policy.event_filter_json or {},
        "segment_target_seconds": policy.segment_target_seconds,
        "pre_roll_seconds": policy.pre_roll_seconds,
        "post_roll_seconds": policy.post_roll_seconds,
        "storage_target_id": (
            str(policy.storage_target_id)
            if policy.storage_target_id is not None
            else None
        ),
        "retention_policy_id": (
            str(policy.retention_policy_id)
            if policy.retention_policy_id is not None
            else None
        ),
        "enabled": policy.enabled,
    }


def _runtime_signature(
    snapshot: dict[str, Any] | None,
) -> tuple[object, ...] | None:
    if snapshot is None:
        return None
    return (
        snapshot["baseline_mode"],
        json.dumps(
            snapshot["schedule"],
            sort_keys=True,
            separators=(",", ":"),
        ),
        snapshot["schedule_timezone"],
        snapshot["event_recording_enabled"],
        snapshot["segment_target_seconds"],
        snapshot["storage_target_id"],
        snapshot["enabled"],
    )


@router.get(
    "/cameras/{camera_id}/recording-policy",
    response_model=RecordingPolicyView,
)
def get_recording_policy(
    camera_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> RecordingPolicyView:
    policy = RecordingPolicyService.get(
        session,
        camera_id=camera_id,
    )
    if policy is None:
        raise ApiError(
            status_code=404,
            code="recording_policy_not_configured",
            message="Recording policy is not configured for this camera.",
        )
    return _policy_view(policy)


@router.put(
    "/cameras/{camera_id}/recording-policy",
    response_model=RecordingPolicyView,
)
def put_recording_policy(
    camera_id: uuid.UUID,
    body: RecordingPolicyPut,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> RecordingPolicyView:
    settings = request.app.state.settings
    existing = RecordingPolicyService.get(
        session,
        camera_id=camera_id,
    )
    before = _audit_snapshot(existing)

    try:
        policy = RecordingPolicyService.put(
            session,
            camera_id=camera_id,
            values={
                "baseline_mode": body.baseline_mode,
                "schedule_json": body.schedule,
                "schedule_timezone": body.schedule_timezone,
                "event_recording_enabled": body.event_recording_enabled,
                "event_filter_json": body.event_filter,
                "segment_target_seconds": body.segment_target_seconds,
                "pre_roll_seconds": body.pre_roll_seconds,
                "post_roll_seconds": body.post_roll_seconds,
                "storage_target_id": body.storage_target_id,
                "retention_policy_id": body.retention_policy_id,
                "enabled": body.enabled,
            },
        )

        can_write_media = (
            policy.enabled
            and (
                policy.baseline_mode != "disabled"
                or policy.event_recording_enabled
            )
        )
        if can_write_media:
            # This also validates the implicit/default target when the policy
            # does not pin one explicitly.
            RecordingStorageResolver.local_target_for_camera(
                session,
                camera_id=camera_id,
            )

        camera = CameraService.get_camera(session, camera_id)
        media_runtime = CameraMediaRuntimeService(settings)
        all_desired_streams = media_runtime.desired_streams(
            session,
            camera=camera,
        )
        desired_recorder = RecordingRuntimeService.desired(
            session,
            settings=settings,
            camera_id=camera_id,
        )
        if desired_recorder is None:
            record_streams = []
        else:
            record_streams = [
                item
                for item in all_desired_streams
                if item.profile_id == desired_recorder.profile_id
            ]
            if not record_streams:
                raise ApiError(
                    status_code=409,
                    code="recording_stream_binding_invalid",
                    message="Camera RECORD stream is not available to the media runtime.",
                )

        after = _audit_snapshot(policy)
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="recording_policy.update",
            resource_type="camera",
            resource_id=camera_id,
            camera_id=camera_id,
            before=before,
            after=after,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    force_reconfigure = (
        _runtime_signature(before)
        != _runtime_signature(after)
    )

    try:
        # No database transaction is held while ZLM performs network/media
        # operations.
        media_runtime.ensure_streams(record_streams)
        runtime_service = RecordingRuntimeService(
            settings,
            mode_tracker=request.app.state.recorder_modes,
        )
        runtime_result = runtime_service.reconcile(
            desired_recorder,
            force_reconfigure=force_reconfigure,
        )
    except ApiError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details={
                **exc.details,
                "policy_persisted": True,
            },
        ) from exc

    policy = RecordingPolicyService.get(
        session,
        camera_id=camera_id,
    )
    assert policy is not None

    return _policy_view(
        policy,
        runtime=RecordingRuntimeView(
            desired_mode=runtime_result.desired_mode,
            recording=runtime_result.observed_recording,
            changed=runtime_result.changed,
            assumed_existing_mode=runtime_result.assumed_existing_mode,
        ),
    )


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
