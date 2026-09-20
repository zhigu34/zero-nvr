from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import (
    get_auth_context,
    get_effective_camera_scope,
    require_camera_permission,
    require_permission,
)
from app.modules.auth.service import AuthContext

from .models import Camera, CameraStreamBinding, CameraStreamProfile, Device
from .schemas import (
    CameraCreate,
    CameraDetail,
    CameraStreamBindingView,
    CameraStreamBindingsUpdate,
    CameraStreamProfileView,
    CameraSummary,
    CameraUpdate,
)
from .service import CameraService


router = APIRouter()


def _camera_summary(session: Session, camera: Camera) -> CameraSummary:
    adapter_type = None
    if camera.device_id is not None:
        device = session.get(Device, camera.device_id)
        if device is not None:
            adapter_type = device.adapter_type

    return CameraSummary(
        id=camera.id,
        name=camera.name,
        enabled=camera.enabled,
        location=camera.location,
        storage_label=camera.storage_label,
        adapter_type=adapter_type,
    )


def _profile_view(profile: CameraStreamProfile) -> CameraStreamProfileView:
    return CameraStreamProfileView(
        id=profile.id,
        name=profile.name,
        adapter_profile_key=profile.adapter_profile_key,
        codec=profile.codec,
        width=profile.width,
        height=profile.height,
        fps=profile.fps,
        bitrate_kbps=profile.bitrate_kbps,
        gop_seconds=profile.gop_seconds,
        audio_codec=profile.audio_codec,
        has_audio=profile.has_audio,
        status=profile.status,
    )


def _binding_view(binding: CameraStreamBinding) -> CameraStreamBindingView:
    return CameraStreamBindingView(
        purpose=binding.purpose,
        stream_profile_id=binding.stream_profile_id,
        selection_mode=binding.selection_mode,
    )


def _camera_detail(session: Session, camera: Camera) -> CameraDetail:
    summary = _camera_summary(session, camera)
    return CameraDetail(
        **summary.model_dump(),
        streams=sorted(
            (_profile_view(item) for item in camera.stream_profiles),
            key=lambda item: item.adapter_profile_key,
        ),
        bindings=sorted(
            (_binding_view(item) for item in camera.stream_bindings),
            key=lambda item: item.purpose,
        ),
    )


def _camera_audit_snapshot(session: Session, camera: Camera) -> dict[str, Any]:
    summary = _camera_summary(session, camera)
    return {
        "name": summary.name,
        "enabled": summary.enabled,
        "location": summary.location,
        "storage_label": summary.storage_label,
        "adapter_type": summary.adapter_type,
    }


def _binding_audit_snapshot(camera: Camera) -> list[dict[str, str]]:
    return sorted(
        [
            {
                "purpose": item.purpose,
                "stream_profile_id": str(item.stream_profile_id),
                "selection_mode": item.selection_mode,
            }
            for item in camera.stream_bindings
        ],
        key=lambda item: item["purpose"],
    )


@router.get("/cameras", response_model=list[CameraSummary])
def list_cameras(
    context: AuthContext = Depends(require_permission("camera.view")),
    session: Session = Depends(get_db_session),
) -> list[CameraSummary]:
    scope = get_effective_camera_scope(context, session)
    allowed = None if scope.all_cameras else scope.camera_ids
    return [
        _camera_summary(session, camera)
        for camera in CameraService.list_cameras(
            session,
            allowed_camera_ids=allowed,
        )
    ]


@router.post("/cameras", response_model=CameraDetail, status_code=201)
def create_camera(
    body: CameraCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("camera.configure")),
    session: Session = Depends(get_db_session),
) -> CameraDetail:
    service = CameraService(request.app.state.settings)
    try:
        secondary_name = (
            body.secondary_stream.name
            if body.secondary_stream is not None
            else None
        )
        secondary_url = (
            body.secondary_stream.rtsp_url.get_secret_value()
            if body.secondary_stream is not None
            else None
        )
        camera = service.create_manual_rtsp_camera(
            session,
            name=body.name,
            location=body.location,
            storage_label=body.storage_label,
            primary_name=body.primary_stream.name,
            primary_url=body.primary_stream.rtsp_url.get_secret_value(),
            secondary_name=secondary_name,
            secondary_url=secondary_url,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="camera.create",
            resource_type="camera",
            resource_id=camera.id,
            camera_id=camera.id,
            after=_camera_audit_snapshot(session, camera),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _camera_detail(session, camera)


@router.get("/cameras/{camera_id}", response_model=CameraDetail)
def get_camera(
    camera_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> CameraDetail:
    return _camera_detail(
        session,
        CameraService.get_camera(session, camera_id),
    )


@router.patch("/cameras/{camera_id}", response_model=CameraDetail)
def update_camera(
    camera_id: uuid.UUID,
    body: CameraUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> CameraDetail:
    try:
        camera = CameraService.get_camera(session, camera_id)
        before = _camera_audit_snapshot(session, camera)
        camera = CameraService.update_camera(
            session,
            camera=camera,
            changes=body.model_dump(exclude_unset=True),
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="camera.update",
            resource_type="camera",
            resource_id=camera.id,
            camera_id=camera.id,
            before=before,
            after=_camera_audit_snapshot(session, camera),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _camera_detail(session, camera)


def _set_camera_enabled(
    *,
    camera_id: uuid.UUID,
    enabled: bool,
    request: Request,
    context: AuthContext,
    session: Session,
) -> CameraDetail:
    try:
        camera = CameraService.get_camera(session, camera_id)
        before = _camera_audit_snapshot(session, camera)
        camera = CameraService.set_enabled(
            session,
            camera=camera,
            enabled=enabled,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="camera.enable" if enabled else "camera.disable",
            resource_type="camera",
            resource_id=camera.id,
            camera_id=camera.id,
            before=before,
            after=_camera_audit_snapshot(session, camera),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _camera_detail(session, camera)


@router.post("/cameras/{camera_id}/enable", response_model=CameraDetail)
def enable_camera(
    camera_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> CameraDetail:
    return _set_camera_enabled(
        camera_id=camera_id,
        enabled=True,
        request=request,
        context=context,
        session=session,
    )


@router.post("/cameras/{camera_id}/disable", response_model=CameraDetail)
def disable_camera(
    camera_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> CameraDetail:
    return _set_camera_enabled(
        camera_id=camera_id,
        enabled=False,
        request=request,
        context=context,
        session=session,
    )


@router.get(
    "/cameras/{camera_id}/streams",
    response_model=list[CameraStreamProfileView],
)
def list_camera_streams(
    camera_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> list[CameraStreamProfileView]:
    camera = CameraService.get_camera(session, camera_id)
    return sorted(
        (_profile_view(item) for item in camera.stream_profiles),
        key=lambda item: item.adapter_profile_key,
    )


@router.get(
    "/cameras/{camera_id}/stream-bindings",
    response_model=list[CameraStreamBindingView],
)
def list_camera_stream_bindings(
    camera_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> list[CameraStreamBindingView]:
    camera = CameraService.get_camera(session, camera_id)
    return sorted(
        (_binding_view(item) for item in camera.stream_bindings),
        key=lambda item: item.purpose,
    )


@router.put(
    "/cameras/{camera_id}/stream-bindings",
    response_model=list[CameraStreamBindingView],
)
def replace_camera_stream_bindings(
    camera_id: uuid.UUID,
    body: CameraStreamBindingsUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> list[CameraStreamBindingView]:
    try:
        camera = CameraService.get_camera(session, camera_id)
        before = _binding_audit_snapshot(camera)
        bindings = CameraService.replace_bindings(
            session,
            camera=camera,
            bindings=[
                (
                    item.purpose,
                    item.stream_profile_id,
                    item.selection_mode,
                )
                for item in body.bindings
            ],
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="camera.stream_bindings.update",
            resource_type="camera",
            resource_id=camera.id,
            camera_id=camera.id,
            before={"bindings": before},
            after={
                "bindings": [
                    {
                        "purpose": item.purpose,
                        "stream_profile_id": str(item.stream_profile_id),
                        "selection_mode": item.selection_mode,
                    }
                    for item in bindings
                ]
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return sorted(
        (_binding_view(item) for item in bindings),
        key=lambda item: item.purpose,
    )
