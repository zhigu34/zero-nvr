from __future__ import annotations

import hmac
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.integrations.zlm import ZlmMediaAccess
from app.modules.cameras.models import CameraStreamProfile
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

    if not ZlmMediaAccess(
        request.app.state.settings
    ).verify(
        app=body.app,
        stream=body.stream,
        params=body.params,
    ):
        return {"code": -1, "msg": "unauthorized"}

    return _ack()


@router.post("/stream-changed")
def zlm_stream_changed(
    body: ZlmStreamChangedHook,
    request: Request,
) -> dict[str, object]:
    _authenticate_hook(request, body.media_server_id)

    # ZLM may publish derived RTMP/HLS/fMP4 registrations for the same source.
    # Only the source-facing RTSP identity is continuity evidence for zero-nvr.
    if body.schema.lower() != "rtsp" or body.app != "zero-nvr":
        return _ack()

    tracker = request.app.state.zlm_continuity
    boundary_at = utc_now()

    if body.regist:
        tracker.registered(
            vhost=body.vhost,
            app=body.app,
            stream=body.stream,
            at=boundary_at,
        )
        return _ack()

    tracker.unregistered(
        vhost=body.vhost,
        app=body.app,
        stream=body.stream,
        at=boundary_at,
    )

    # Source unregister proves only that a continuity generation ended. It does
    # not by itself prove an exact canonical segment boundary. The last segment
    # therefore remains PROVISIONAL until explicit-stop or recovery evidence.
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
            request.app.state.zlm_continuity.remember_segment(
                vhost=body.vhost,
                app=body.app,
                stream=body.stream,
                continuity_id=resolution.continuity_id,
                segment_id=result.segment.id,
            )

        session.commit()
    except Exception:
        session.rollback()
        raise

    return _ack()
