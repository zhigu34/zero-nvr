from __future__ import annotations

import hmac
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.integrations.zlm import ZlmMediaAccess
from app.modules.cameras.models import (
    CameraStreamBinding,
    CameraStreamProfile,
)
from app.modules.events.system import SystemEventService
from app.modules.recordings.catalog import (
    FinalizedRecordingEvidence,
    RecordingCatalogService,
)
from app.modules.recordings.models import RecordingPolicy


router = APIRouter()


class ZlmHookBase(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    media_server_id: str = Field(
        alias="mediaServerId",
        min_length=1,
        max_length=512,
    )


class ZlmServerStartedHook(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )

    media_server_id: str = Field(
        validation_alias=AliasChoices(
            "mediaServerId",
            "general.mediaServerId",
        ),
        min_length=1,
        max_length=512,
    )


class ZlmStreamChangedHook(ZlmHookBase):
    schema: str = Field(min_length=1, max_length=32)
    vhost: str = Field(default="__defaultVhost__", max_length=256)
    app: str = Field(min_length=1, max_length=128)
    stream: str = Field(min_length=1, max_length=256)
    regist: bool


class ZlmPlayHook(ZlmHookBase):
    app: str = Field(min_length=1, max_length=128)
    stream: str = Field(min_length=1, max_length=256)
    params: str = Field(default="", max_length=4096)


class ZlmRecordMp4Hook(ZlmHookBase):
    vhost: str = Field(default="__defaultVhost__", max_length=256)
    app: str = Field(min_length=1, max_length=128)
    stream: str = Field(min_length=1, max_length=256)
    start_time: float = Field(gt=0)
    time_len: float = Field(gt=0)
    file_size: int = Field(ge=0)
    file_path: str = Field(min_length=1, max_length=4096)


def _authenticate_hook(
    request: Request,
    media_server_id: str,
) -> None:
    configured = request.app.state.settings.zlm_hook_secret
    if configured is None:
        raise ApiError(
            status_code=503,
            code="zlm_hook_not_configured",
            message="ZLMediaKit hook authentication is not configured.",
        )

    expected = configured.get_secret_value()
    if not hmac.compare_digest(
        media_server_id.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise ApiError(
            status_code=401,
            code="zlm_hook_unauthorized",
            message="ZLMediaKit hook authentication failed.",
        )


def _ack() -> dict[str, object]:
    return {"code": 0, "msg": "success"}


def _recording_camera_id(
    session: Session,
    *,
    stream: str,
):
    """Resolve a managed RECORD binding without treating other ZLM streams as outages."""

    try:
        profile_id = RecordingCatalogService.profile_id_from_stream(
            stream
        )
    except ApiError:
        return None

    binding = session.scalar(
        select(CameraStreamBinding).where(
            CameraStreamBinding.stream_profile_id == profile_id,
            CameraStreamBinding.purpose == "RECORD",
        )
    )
    return binding.camera_id if binding is not None else None


@router.post("/server-started")
def zlm_server_started(
    body: ZlmServerStartedHook,
    request: Request,
) -> dict[str, object]:
    _authenticate_hook(
        request,
        body.media_server_id,
    )

    request.app.state.zlm_continuity.reset()
    request.app.state.zlm_health.clear()
    try:
        request.app.state.runtime_reconciler.enqueue_all()
    except Exception:
        request.app.state.logger.warning(
            "ZLM restart recovery enqueue failed"
        )
    return _ack()


@router.post("/play")
def zlm_play(
    body: ZlmPlayHook,
    request: Request,
) -> dict[str, object]:
    _authenticate_hook(request, body.media_server_id)

    if body.app not in {
        "zero-nvr",
        "zero-nvr-vod",
        "zero-nvr-compat",
    }:
        return {"code": -1, "msg": "unauthorized"}

    access = ZlmMediaAccess(
        request.app.state.settings
    )
    if not access.verify(
        app=body.app,
        stream=body.stream,
        params=body.params,
    ):
        return {"code": -1, "msg": "unauthorized"}

    media_session_id = access.session_id_from_params(
        body.params
    )
    if (
        media_session_id is not None
        and not request.app.state.media_sessions.active(
            media_session_id
        )
    ):
        return {"code": -1, "msg": "unauthorized"}

    return _ack()


@router.post("/stream-changed")
def zlm_stream_changed(
    body: ZlmStreamChangedHook,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    _authenticate_hook(request, body.media_server_id)

    # ZLM may publish derived RTMP/HLS/fMP4 registrations for the same source.
    # Only the source-facing RTSP identity is continuity evidence for zero-nvr.
    if body.schema.lower() != "rtsp" or body.app != "zero-nvr":
        return _ack()

    tracker = request.app.state.zlm_continuity
    health = request.app.state.zlm_health
    boundary_at = utc_now()
    try:
        profile_id = (
            RecordingCatalogService
            .profile_id_from_stream(
                body.stream
            )
        )
    except ApiError:
        profile_id = None

    if body.regist:
        continuity_id = tracker.registered(
            vhost=body.vhost,
            app=body.app,
            stream=body.stream,
            at=boundary_at,
        )
        if profile_id is not None:
            health.stream_registered(
                profile_id,
                at=boundary_at,
                continuity_id=(
                    continuity_id
                ),
            )
    else:
        continuity_id = tracker.unregistered(
            vhost=body.vhost,
            app=body.app,
            stream=body.stream,
            at=boundary_at,
        )
        if profile_id is not None:
            health.stream_unregistered(
                profile_id,
                at=boundary_at,
                continuity_id=(
                    continuity_id
                ),
            )

    # Persist only meaningful RECORD-source transitions. The canonical Event
    # interval is intentionally separate from high-frequency runtime telemetry:
    # unregister opens source_lost and the next registration closes it.
    camera_id = None
    try:
        camera_id = _recording_camera_id(
            session,
            stream=body.stream,
        )
        if camera_id is not None:
            transition = (
                SystemEventService.source_recovered
                if body.regist
                else SystemEventService.source_lost
            )
            transition(
                session,
                camera_id=camera_id,
                observed_at=boundary_at,
                stream=body.stream,
                app=body.app,
                vhost=body.vhost,
            )
        session.commit()
    except Exception:
        session.rollback()
        request.app.state.logger.warning(
            "recording source health persistence failed after ZLM stream transition",
            extra={
                "stream": body.stream,
                "transition": (
                    "registered"
                    if body.regist
                    else "unregistered"
                ),
            },
        )

    if body.regist and camera_id is not None:
        # ZLM owns reconnect. Re-apply the still-persisted RecordingPolicy and
        # Trigger intent through the normal idempotent runtime reconcilers.
        dispatcher = request.app.state.recording_tasks
        for operation, callback in (
            (
                "runtime",
                dispatcher.reconcile_runtime,
            ),
            (
                "prebuffer",
                dispatcher.reconcile_camera,
            ),
        ):
            try:
                callback(camera_id)
            except Exception:
                request.app.state.logger.warning(
                    "recording recovery reconcile enqueue failed after ZLM source registration",
                    extra={
                        "camera_id": str(camera_id),
                        "stream": body.stream,
                        "operation": operation,
                    },
                )

    # An unregister callback is a continuity and health boundary, not exact
    # media timing proof. Finalized media hooks still determine the physical
    # tail and completion_reason=source_lost without stretching segment time.
    return _ack()


@router.post("/record-mp4")
def zlm_record_mp4(
    body: ZlmRecordMp4Hook,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    _authenticate_hook(request, body.media_server_id)

    raw_started = datetime.fromtimestamp(
        body.start_time,
        tz=UTC,
    )
    resolution = request.app.state.zlm_continuity.resolve_record(
        vhost=body.vhost,
        app=body.app,
        stream=body.stream,
        started_at=raw_started,
    )

    try:
        settings = request.app.state.settings
        prebuffer_root = settings.prebuffer_dir.resolve()
        hook_path = Path(body.file_path).resolve(strict=False)
        is_prebuffer = False
        try:
            hook_path.relative_to(prebuffer_root)
            is_prebuffer = True
        except ValueError:
            pass

        if is_prebuffer:
            if body.app != RecordingCatalogService.expected_app:
                return _ack()

            profile_id = RecordingCatalogService.profile_id_from_stream(
                body.stream
            )
            profile = session.get(CameraStreamProfile, profile_id)
            if profile is None:
                raise ApiError(
                    status_code=422,
                    code="recording_stream_unknown",
                    message="Recording stream profile does not exist.",
                )

            policy = session.scalar(
                select(RecordingPolicy).where(
                    RecordingPolicy.camera_id == profile.camera_id
                )
            )
            if (
                policy is None
                or not policy.enabled
                or not policy.event_recording_enabled
            ):
                # A stale finalized tmpfs hook can arrive after policy mode
                # changed. It remains ephemeral and is not promoted/canonical.
                return _ack()

            fragment = request.app.state.prebuffer_fragments.observe(
                camera_id=profile.camera_id,
                profile_id=profile.id,
                continuity_id=(
                    resolution.continuity_id
                    if resolution is not None
                    else None
                ),
                vhost=body.vhost,
                app=body.app,
                stream=body.stream,
                file_path=body.file_path,
                start_time_epoch=body.start_time,
                duration_seconds=body.time_len,
                size_bytes=body.file_size,
            )
            request.app.state.recording_tasks.finalized_prebuffer_fragment(
                fragment
            )
            request.app.state.zlm_health.recording_finalized(
                profile.id,
                continuity_id=(
                    resolution.continuity_id
                    if resolution is not None
                    else None
                ),
            )
            return _ack()

        result = RecordingCatalogService.ingest_finalized(
            session,
            evidence=FinalizedRecordingEvidence(
                vhost=body.vhost,
                app=body.app,
                stream=body.stream,
                start_time_epoch=body.start_time,
                duration_seconds=body.time_len,
                file_size=body.file_size,
                file_path=body.file_path,
            ),
            previous_segment_id=(
                resolution.previous_segment_id
                if resolution is not None
                else None
            ),
        )

        if resolution is not None and result.segment is not None:
            remembered = (
                request.app.state.zlm_continuity
                .remember_segment(
                    vhost=body.vhost,
                    app=body.app,
                    stream=body.stream,
                    continuity_id=(
                        resolution.continuity_id
                    ),
                    segment_id=result.segment.id,
                    started_at=(
                        result.segment.started_at
                    ),
                )
            )
            if (
                remembered
                and resolution.closed_at
                is not None
            ):
                RecordingCatalogService.mark_source_loss_tail(
                    session,
                    previous_segment_id=(
                        resolution.previous_segment_id
                    ),
                    segment_id=(
                        result.segment.id
                    ),
                )

        session.commit()
        if result.segment is not None:
            request.app.state.zlm_health.recording_finalized(
                result.segment.stream_profile_id,
                continuity_id=(
                    resolution.continuity_id
                    if resolution is not None
                    else None
                ),
            )
    except Exception:
        session.rollback()
        raise

    return _ack()
