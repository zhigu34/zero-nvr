from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.integrations.zlm import ZlmIntegrationError
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import (
    get_auth_context,
    get_effective_camera_scope,
    require_camera_permission,
    require_permission,
)
from app.modules.auth.service import AuthContext
from app.modules.cameras.media_runtime import CameraMediaRuntimeService
from app.modules.cameras.service import CameraService
from app.modules.storage.recording_resolver import RecordingStorageResolver

from .models import (
    RecordingPolicy,
    RecordingProtection,
    RecordingTrigger,
)
from .playback import (
    GapPlan,
    PendingPlan,
    PlayablePlan,
    PlaybackResolverService,
)
from .playback_cache import PlaybackCacheService
from .policy import RecordingPolicyService
from .protection import RecordingProtectionService
from .query import RecordingCatalogQueryService
from .runtime import RecordingRuntimeService
from .schemas import (
    PlaybackGapView,
    PlaybackPendingView,
    PlaybackPlayableView,
    PlaybackResolveRequest,
    PlaybackResolveView,
    PlaybackTimelineView,
    RecordingPolicyPut,
    RecordingLocationView,
    RecordingProtectionCreate,
    RecordingProtectionUpdate,
    RecordingProtectionView,
    RecordingPolicyView,
    RecordingRuntimeView,
    RecordingSegmentPage,
    RecordingSegmentView,
    RecordingTriggerCreate,
    RecordingTriggerView,
)
from .timeline import PlaybackTimelineService
from .triggers import RecordingTriggerService


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






def _segment_view(segment) -> RecordingSegmentView:
    return RecordingSegmentView(
        id=segment.id,
        camera_id=segment.camera_id,
        stream_profile_id=segment.stream_profile_id,
        start_at=segment.started_at,
        end_at=segment.ended_at,
        duration_ms=segment.duration_ms,
        timing_status=segment.timing_status,
        timing_source=segment.timing_source,
        recording_reasons=segment.recording_reasons_json or [],
        size_bytes=segment.size_bytes,
        codec=segment.codec,
        container=segment.container,
        integrity_status=segment.integrity_status,
        completion_reason=segment.completion_reason,
        created_at=segment.created_at,
    )


def _location_view(location) -> RecordingLocationView:
    target = location.storage_target
    return RecordingLocationView(
        id=location.id,
        recording_segment_id=location.recording_segment_id,
        storage_target_id=location.storage_target_id,
        storage_target_name=target.name,
        storage_type=target.type,
        storage_role=target.role,
        object_path=location.object_path,
        state=location.state,
        size_bytes=location.size_bytes,
        checksum=location.checksum,
        verified_at=location.verified_at,
        created_at=location.created_at,
        deleted_at=location.deleted_at,
    )


def _require_segment_scope(
    *,
    context: AuthContext,
    session: Session,
    camera_id: uuid.UUID,
) -> None:
    scope = get_effective_camera_scope(context, session)
    if not scope.allows(camera_id):
        raise ApiError(
            status_code=404,
            code="recording_not_found",
            message="Recording segment was not found.",
        )


def _protection_view(
    protection: RecordingProtection,
) -> RecordingProtectionView:
    return RecordingProtectionView(
        id=protection.id,
        camera_id=protection.camera_id,
        started_at=protection.started_at,
        ended_at=protection.ended_at,
        reason=protection.reason,
        created_by=protection.created_by,
        expires_at=protection.expires_at,
        created_at=protection.created_at,
        updated_at=protection.updated_at,
    )


def _protection_audit_snapshot(
    protection: RecordingProtection,
) -> dict[str, Any]:
    return {
        "camera_id": str(protection.camera_id),
        "started_at": protection.started_at.isoformat(),
        "ended_at": protection.ended_at.isoformat(),
        "reason": protection.reason,
        "created_by": (
            str(protection.created_by)
            if protection.created_by is not None
            else None
        ),
        "expires_at": (
            protection.expires_at.isoformat()
            if protection.expires_at is not None
            else None
        ),
    }


def _trigger_view(
    trigger: RecordingTrigger,
) -> RecordingTriggerView:
    return RecordingTriggerView(
        id=trigger.id,
        camera_id=trigger.camera_id,
        type=trigger.type,
        source=trigger.source,
        requested_at=trigger.requested_at,
        pre_roll_seconds=trigger.pre_roll_seconds,
        post_roll_seconds=trigger.post_roll_seconds,
        planned_start_at=trigger.planned_start_at,
        planned_end_at=trigger.planned_end_at,
        state=trigger.state,
        reason=trigger.reason,
        correlation_id=trigger.correlation_id,
    )


def _trigger_audit_snapshot(
    trigger: RecordingTrigger,
) -> dict[str, Any]:
    return {
        "camera_id": str(trigger.camera_id),
        "type": trigger.type,
        "source": trigger.source,
        "requested_at": trigger.requested_at.isoformat(),
        "planned_start_at": trigger.planned_start_at.isoformat(),
        "planned_end_at": (
            trigger.planned_end_at.isoformat()
            if trigger.planned_end_at is not None
            else None
        ),
        "pre_roll_seconds": trigger.pre_roll_seconds,
        "post_roll_seconds": trigger.post_roll_seconds,
        "state": trigger.state,
        "reason": trigger.reason,
        "correlation_id": trigger.correlation_id,
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
        next_policy_boundary = (
            RecordingPolicyService.next_baseline_transition(
                policy,
                after=datetime.now(UTC),
            )
            if policy.enabled
            and policy.baseline_mode == "schedule"
            else None
        )
        policy_id = policy.id
        policy_version = policy.updated_at.isoformat()
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

    if next_policy_boundary is not None:
        try:
            request.app.state.recording_tasks.schedule_policy(
                policy_id=policy_id,
                policy_version=policy_version,
                eta=next_policy_boundary,
            )
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="recording_task_queue_unavailable",
                message="Recording policy was saved but its next schedule boundary could not be queued.",
                details={
                    "policy_persisted": True,
                    "policy_id": str(policy_id),
                },
            ) from exc

    try:
        # No database transaction is held while ZLM performs network/media
        # operations.
        if desired_recorder is not None and desired_recorder.mode != "off":
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
    except ZlmIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={"policy_persisted": True},
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







@router.post(
    "/cameras/{camera_id}/recording-protections",
    response_model=RecordingProtectionView,
    status_code=201,
)
def create_recording_protection(
    camera_id: uuid.UUID,
    body: RecordingProtectionCreate,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("recording.protect")
    ),
    session: Session = Depends(get_db_session),
) -> RecordingProtectionView:
    try:
        protection = RecordingProtectionService.create(
            session,
            camera_id=camera_id,
            started_at=body.started_at,
            ended_at=body.ended_at,
            reason=body.reason,
            created_by=context.user.id,
            expires_at=body.expires_at,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="recording_protection.create",
            resource_type="recording_protection",
            resource_id=protection.id,
            camera_id=camera_id,
            after=_protection_audit_snapshot(protection),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _protection_view(protection)


@router.get(
    "/cameras/{camera_id}/recording-protections",
    response_model=list[RecordingProtectionView],
)
def list_recording_protections(
    camera_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_camera_permission("recording.view")
    ),
    session: Session = Depends(get_db_session),
) -> list[RecordingProtectionView]:
    CameraService.get_camera(session, camera_id)
    return [
        _protection_view(item)
        for item in RecordingProtectionService.list_for_camera(
            session,
            camera_id=camera_id,
        )
    ]


@router.put(
    "/recording-protections/{protection_id}",
    response_model=RecordingProtectionView,
)
def update_recording_protection(
    protection_id: uuid.UUID,
    body: RecordingProtectionUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("recording.protect")
    ),
    session: Session = Depends(get_db_session),
) -> RecordingProtectionView:
    protection = RecordingProtectionService.get(
        session,
        protection_id,
    )
    scope = get_effective_camera_scope(
        context,
        session,
    )
    if not scope.allows(protection.camera_id):
        session.commit()
        raise ApiError(
            status_code=404,
            code="recording_protection_not_found",
            message="Recording protection was not found.",
        )

    before = _protection_audit_snapshot(protection)
    try:
        protection = RecordingProtectionService.update(
            session,
            protection=protection,
            started_at=body.started_at,
            ended_at=body.ended_at,
            reason=body.reason,
            expires_at=body.expires_at,
        )
        after = _protection_audit_snapshot(protection)
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="recording_protection.update",
            resource_type="recording_protection",
            resource_id=protection.id,
            camera_id=protection.camera_id,
            before=before,
            after=after,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _protection_view(protection)


@router.delete(
    "/recording-protections/{protection_id}",
    status_code=204,
)
def delete_recording_protection(
    protection_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("recording.protect")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    protection = RecordingProtectionService.get(
        session,
        protection_id,
    )
    scope = get_effective_camera_scope(
        context,
        session,
    )
    if not scope.allows(protection.camera_id):
        session.commit()
        raise ApiError(
            status_code=404,
            code="recording_protection_not_found",
            message="Recording protection was not found.",
        )

    before = _protection_audit_snapshot(protection)
    resource_id = protection.id
    camera_id = protection.camera_id
    try:
        RecordingProtectionService.delete(
            session,
            protection=protection,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="recording_protection.delete",
            resource_type="recording_protection",
            resource_id=resource_id,
            camera_id=camera_id,
            before=before,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return Response(status_code=204)


@router.post(
    "/cameras/{camera_id}/recording-triggers",
    response_model=RecordingTriggerView,
    status_code=201,
)
def create_recording_trigger(
    camera_id: uuid.UUID,
    body: RecordingTriggerCreate,
    request: Request,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    context: AuthContext = Depends(
        require_camera_permission("camera.control")
    ),
    session: Session = Depends(get_db_session),
) -> RecordingTriggerView:
    try:
        trigger, created = RecordingTriggerService.create_manual(
            session,
            camera_id=camera_id,
            reason=body.reason,
            idempotency_key=idempotency_key,
        )
        if created:
            append_audit_event(
                session,
                request=request,
                actor_id=context.user.id,
                action="recording_trigger.create",
                resource_type="recording_trigger",
                resource_id=trigger.id,
                camera_id=camera_id,
                after=_trigger_audit_snapshot(trigger),
            )
        session.commit()
    except Exception:
        session.rollback()
        raise

    try:
        request.app.state.recording_tasks.reconcile_camera(
            camera_id
        )
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="recording_task_queue_unavailable",
            message="Recording trigger was saved but background reconciliation could not be queued.",
            details={
                "trigger_persisted": True,
                "trigger_id": str(trigger.id),
            },
        ) from exc

    return _trigger_view(trigger)


@router.get(
    "/cameras/{camera_id}/recording-triggers",
    response_model=list[RecordingTriggerView],
)
def list_recording_triggers(
    camera_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_camera_permission("recording.view")
    ),
    session: Session = Depends(get_db_session),
) -> list[RecordingTriggerView]:
    CameraService.get_camera(session, camera_id)
    return [
        _trigger_view(item)
        for item in RecordingTriggerService.list_for_camera(
            session,
            camera_id=camera_id,
        )
    ]


@router.post(
    "/recording-triggers/{trigger_id}/stop",
    response_model=RecordingTriggerView,
)
def stop_recording_trigger(
    trigger_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("camera.control")
    ),
    session: Session = Depends(get_db_session),
) -> RecordingTriggerView:
    trigger = RecordingTriggerService.get(
        session,
        trigger_id,
    )
    scope = get_effective_camera_scope(
        context,
        session,
    )
    if not scope.allows(trigger.camera_id):
        session.commit()
        raise ApiError(
            status_code=404,
            code="recording_trigger_not_found",
            message="Recording trigger was not found.",
        )

    before = _trigger_audit_snapshot(trigger)
    try:
        trigger = RecordingTriggerService.stop_manual(
            session,
            trigger=trigger,
        )
        after = _trigger_audit_snapshot(trigger)
        if before != after:
            append_audit_event(
                session,
                request=request,
                actor_id=context.user.id,
                action="recording_trigger.stop",
                resource_type="recording_trigger",
                resource_id=trigger.id,
                camera_id=trigger.camera_id,
                before=before,
                after=after,
            )
        camera_id = trigger.camera_id
        session.commit()
    except Exception:
        session.rollback()
        raise

    try:
        request.app.state.recording_tasks.reconcile_camera(
            camera_id
        )
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="recording_task_queue_unavailable",
            message="Recording trigger was stopped but background reconciliation could not be queued.",
            details={
                "trigger_persisted": True,
                "trigger_id": str(trigger.id),
            },
        ) from exc

    return _trigger_view(trigger)




@router.get(
    "/cameras/{camera_id}/recordings",
    response_model=RecordingSegmentPage,
)
def list_camera_recordings(
    camera_id: uuid.UUID,
    from_at: datetime | None = Query(
        default=None,
        alias="from",
    ),
    to_at: datetime | None = Query(
        default=None,
        alias="to",
    ),
    cursor: str | None = None,
    limit: int = 100,
    _context: AuthContext = Depends(
        require_camera_permission("recording.view")
    ),
    session: Session = Depends(get_db_session),
) -> RecordingSegmentPage:
    CameraService.get_camera(session, camera_id)
    start_at = (
        _normalized_utc(from_at, field_name="from")
        if from_at is not None
        else None
    )
    end_at = (
        _normalized_utc(to_at, field_name="to")
        if to_at is not None
        else None
    )
    page = RecordingCatalogQueryService.list_camera(
        session,
        camera_id=camera_id,
        start_at=start_at,
        end_at=end_at,
        cursor=cursor,
        limit=limit,
    )
    return RecordingSegmentPage(
        items=[_segment_view(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/recordings/{segment_id}",
    response_model=RecordingSegmentView,
)
def get_recording_segment(
    segment_id: uuid.UUID,
    context: AuthContext = Depends(
        require_permission("recording.view")
    ),
    session: Session = Depends(get_db_session),
) -> RecordingSegmentView:
    segment = RecordingCatalogQueryService.get_segment(
        session,
        segment_id,
    )
    _require_segment_scope(
        context=context,
        session=session,
        camera_id=segment.camera_id,
    )
    return _segment_view(segment)


@router.get(
    "/recordings/{segment_id}/locations",
    response_model=list[RecordingLocationView],
)
def get_recording_locations(
    segment_id: uuid.UUID,
    context: AuthContext = Depends(
        require_permission("recording.view")
    ),
    session: Session = Depends(get_db_session),
) -> list[RecordingLocationView]:
    segment = RecordingCatalogQueryService.get_segment(
        session,
        segment_id,
    )
    _require_segment_scope(
        context=context,
        session=session,
        camera_id=segment.camera_id,
    )
    return [
        _location_view(item)
        for item in RecordingCatalogQueryService.locations(
            session,
            segment_id=segment_id,
        )
    ]




@router.post(
    "/cameras/{camera_id}/playback/resolve",
    response_model=PlaybackResolveView,
)
def resolve_camera_playback(
    camera_id: uuid.UUID,
    body: PlaybackResolveRequest,
    request: Request,
    _context: AuthContext = Depends(
        require_camera_permission("recording.view")
    ),
    session: Session = Depends(get_db_session),
) -> PlaybackResolveView:
    at = _normalized_utc(body.at, field_name="at")
    CameraService.get_camera(session, camera_id)

    plan = PlaybackResolverService.plan(
        session,
        camera_id=camera_id,
        at=at,
        settings=request.app.state.settings,
    )
    # No SQLite transaction remains open while filesystem/ZLM work runs.
    session.commit()

    if isinstance(plan, GapPlan):
        return PlaybackGapView(
            reason=plan.reason,
            previous_at=plan.previous_at,
            next_at=plan.next_at,
        )

    if isinstance(plan, PendingPlan):
        cache = PlaybackCacheService(request.app.state.settings)
        if cache.reserve_restore(segment_id=plan.segment_id):
            try:
                request.app.state.storage_tasks.restore_playback_segment(
                    segment_id=plan.segment_id,
                )
            except Exception:
                cache.clear_restore_request(
                    segment_id=plan.segment_id,
                )
                raise
        return PlaybackPendingView(
            reason=plan.reason,
            segment_id=plan.segment_id,
        )

    assert isinstance(plan, PlayablePlan)
    try:
        url, expires_at = PlaybackResolverService.activate(
            request.app.state.settings,
            plan,
        )
    except ZlmIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
        ) from exc

    return PlaybackPlayableView(
        segment_id=plan.segment_id,
        segment_start_at=plan.segment_start_at,
        offset_ms=plan.offset_ms,
        url=url,
        expires_at=expires_at,
        codec=plan.codec,
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
