from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.integrations.onvif import (
    OnvifAdapter,
    OnvifInspection,
    OnvifIntegrationError,
)
from app.integrations.zlm import (
    ZlmAdapter,
    ZlmIntegrationError,
    ZlmMediaProbe,
    ZlmTrackProbe,
)
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import (
    get_auth_context,
    get_effective_camera_scope,
    require_camera_permission,
    require_permission,
)
from app.modules.auth.service import AuthContext

from .discovery_service import CameraDiscoveryService
from .media_runtime import CameraMediaRuntimeService
from .onvif_onboarding import OnvifOnboardingService
from .models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    DiscoveryCandidate,
    DiscoverySession,
)
from .schemas import (
    CameraCreate,
    CameraDetail,
    CameraLiveStreamView,
    CameraProbeResult,
    CameraProbeStreamView,
    CameraProbeTrackView,
    CameraStreamBindingView,
    CameraStreamBindingsUpdate,
    CameraStreamProfileView,
    CameraSummary,
    CameraUpdate,
    DiscoveryCandidateView,
    DiscoverySessionView,
    OnvifCameraImportInput,
    OnvifCameraTestInput,
    OnvifDeviceInfoView,
    OnvifImportResult,
    OnvifInspectionView,
    OnvifProfileView,
)
from .service import CameraService


router = APIRouter()


def _probe_track_view(track: ZlmTrackProbe | None) -> CameraProbeTrackView | None:
    if track is None:
        return None
    return CameraProbeTrackView(
        kind=track.kind,
        codec=track.codec,
        ready=track.ready,
        width=track.width,
        height=track.height,
        fps=track.fps,
        gop_seconds=track.gop_seconds,
        sample_rate=track.sample_rate,
        channels=track.channels,
    )


def _probe_stream_view(
    *,
    role: str,
    name: str,
    probe: ZlmMediaProbe,
) -> CameraProbeStreamView:
    return CameraProbeStreamView(
        role=role,
        name=name,
        video=_probe_track_view(probe.video),
        audio=_probe_track_view(probe.audio),
    )


def _onvif_inspection_view(
    inspection: OnvifInspection,
) -> OnvifInspectionView:
    return OnvifInspectionView(
        device=OnvifDeviceInfoView(
            manufacturer=inspection.device.manufacturer,
            model=inspection.device.model,
            firmware_version=inspection.device.firmware_version,
            serial_number=inspection.device.serial_number,
            hardware_id=inspection.device.hardware_id,
        ),
        capabilities=list(inspection.capabilities),
        profiles=[
            OnvifProfileView(
                token=profile.token,
                name=profile.name,
                video_source_token=profile.video_source_token,
                codec=profile.codec,
                width=profile.width,
                height=profile.height,
                fps=profile.fps,
                bitrate_kbps=profile.bitrate_kbps,
                gop_seconds=profile.gop_seconds,
                audio_codec=profile.audio_codec,
                has_audio=profile.has_audio,
                stream_uri_available=profile.stream_uri_available,
            )
            for profile in inspection.profiles
        ],
    )


def _discovery_candidate_view(
    candidate: DiscoveryCandidate,
) -> DiscoveryCandidateView:
    metadata = candidate.metadata_json or {}
    raw_port = metadata.get("port")
    port = raw_port if isinstance(raw_port, int) else None
    raw_url = metadata.get("device_service_url")
    device_service_url = raw_url if isinstance(raw_url, str) else None
    display_info = (
        candidate.display_info
        if isinstance(candidate.display_info, dict)
        else {}
    )
    return DiscoveryCandidateView(
        id=candidate.id,
        candidate_key=candidate.candidate_key,
        host=candidate.host,
        port=port,
        device_service_url=device_service_url,
        display_info=display_info,
        state=candidate.state,
    )


def _discovery_session_view(
    discovery: DiscoverySession,
) -> DiscoverySessionView:
    return DiscoverySessionView(
        id=discovery.id,
        method=discovery.method,
        status=discovery.status,
        started_at=discovery.started_at,
        completed_at=discovery.completed_at,
        candidates=sorted(
            (
                _discovery_candidate_view(candidate)
                for candidate in discovery.candidates
            ),
            key=lambda item: item.candidate_key,
        ),
    )


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


@router.post("/cameras/test", response_model=CameraProbeResult)
def test_camera_configuration(
    body: CameraCreate,
    request: Request,
    _context: AuthContext = Depends(require_permission("camera.configure")),
) -> CameraProbeResult:
    streams: list[tuple[str, str, str]] = [
        (
            "primary",
            body.primary_stream.name,
            body.primary_stream.rtsp_url.get_secret_value(),
        )
    ]
    if body.secondary_stream is not None:
        streams.append(
            (
                "secondary",
                body.secondary_stream.name,
                body.secondary_stream.rtsp_url.get_secret_value(),
            )
        )

    # Validate all source URIs before opening any temporary ZLM proxy.
    for _role, _name, source_url in streams:
        CameraService.validate_rtsp_url(source_url)

    results: list[CameraProbeStreamView] = []
    try:
        with ZlmAdapter(request.app.state.settings) as zlm:
            for role, name, source_url in streams:
                try:
                    probe = zlm.probe_rtsp_source(source_url)
                except ZlmIntegrationError as exc:
                    raise ApiError(
                        status_code=exc.status_code,
                        code=exc.code,
                        message=str(exc),
                        details={"stream": role},
                    ) from exc

                results.append(
                    _probe_stream_view(
                        role=role,
                        name=name,
                        probe=probe,
                    )
                )
    except ZlmIntegrationError as exc:
        # Covers bootstrap/configuration failures such as missing API secret.
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc

    return CameraProbeResult(streams=results)


@router.post(
    "/cameras/onvif/import",
    response_model=OnvifImportResult,
    status_code=201,
)
async def import_onvif_camera(
    body: OnvifCameraImportInput,
    request: Request,
    context: AuthContext = Depends(require_permission("camera.configure")),
    session: Session = Depends(get_db_session),
) -> OnvifImportResult:
    try:
        inspection = await OnvifAdapter(
            request.app.state.settings
        ).inspect_device(
            host=body.host,
            port=body.port,
            username=body.username,
            password=body.password.get_secret_value(),
        )
    except OnvifIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc

    service = OnvifOnboardingService(request.app.state.settings)
    try:
        device, cameras = service.import_device(
            session,
            inspection=inspection,
            host=body.host,
            port=body.port,
            username=body.username,
            password=body.password.get_secret_value(),
            base_name=body.name,
            location=body.location,
            storage_label=body.storage_label,
            selected_profile_tokens=body.profile_tokens,
            discovery_candidate_id=body.discovery_candidate_id,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="camera.onvif.import",
            resource_type="device",
            resource_id=device.id,
            metadata={
                "camera_ids": [str(camera.id) for camera in cameras],
                "camera_count": len(cameras),
                "profile_count": sum(
                    len(camera.stream_profiles)
                    for camera in cameras
                ),
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return OnvifImportResult(
        device_id=device.id,
        cameras=[
            _camera_detail(session, camera)
            for camera in cameras
        ],
    )


@router.post("/cameras/onvif/test", response_model=OnvifInspectionView)
async def test_onvif_camera(
    body: OnvifCameraTestInput,
    request: Request,
    _context: AuthContext = Depends(require_permission("camera.configure")),
) -> OnvifInspectionView:
    try:
        inspection = await OnvifAdapter(
            request.app.state.settings
        ).inspect_device(
            host=body.host,
            port=body.port,
            username=body.username,
            password=body.password.get_secret_value(),
        )
    except OnvifIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc

    return _onvif_inspection_view(inspection)


@router.post(
    "/cameras/discovery",
    response_model=DiscoverySessionView,
    status_code=201,
)
async def run_camera_discovery(
    request: Request,
    context: AuthContext = Depends(require_permission("camera.configure")),
    session: Session = Depends(get_db_session),
) -> DiscoverySessionView:
    try:
        discovery = CameraDiscoveryService.start(
            session,
            created_by=context.user.id,
        )
        session.commit()
        discovery_id = discovery.id
    except Exception:
        session.rollback()
        raise

    try:
        candidates = await OnvifAdapter(
            request.app.state.settings
        ).discover()
    except OnvifIntegrationError as exc:
        try:
            failed = CameraDiscoveryService.fail(
                session,
                discovery_id=discovery_id,
            )
            append_audit_event(
                session,
                request=request,
                actor_id=context.user.id,
                action="camera.discovery.run",
                resource_type="discovery_session",
                resource_id=failed.id,
                result="failure",
                reason=exc.code,
                metadata={"method": "onvif_ws_discovery"},
            )
            session.commit()
        except Exception:
            session.rollback()

        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={"discovery_id": str(discovery_id)},
        ) from exc

    try:
        completed = CameraDiscoveryService.complete(
            session,
            discovery_id=discovery_id,
            candidates=candidates,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="camera.discovery.run",
            resource_type="discovery_session",
            resource_id=completed.id,
            metadata={
                "method": "onvif_ws_discovery",
                "candidate_count": len(candidates),
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _discovery_session_view(completed)


@router.get(
    "/cameras/discovery/{discovery_id}",
    response_model=DiscoverySessionView,
)
def get_camera_discovery(
    discovery_id: uuid.UUID,
    _context: AuthContext = Depends(require_permission("camera.configure")),
    session: Session = Depends(get_db_session),
) -> DiscoverySessionView:
    discovery = CameraDiscoveryService.get(session, discovery_id)
    return _discovery_session_view(discovery)


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



@router.get(
    "/cameras/{camera_id}/live",
    response_model=CameraLiveStreamView,
)
def get_camera_live_stream(
    camera_id: uuid.UUID,
    request: Request,
    quality: Literal["auto", "high", "low"] = Query(default="auto"),
    _context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> CameraLiveStreamView:
    camera = CameraService.get_camera(session, camera_id)
    if not camera.enabled:
        raise ApiError(
            status_code=409,
            code="camera_disabled",
            message="Camera is disabled.",
        )

    priorities = {
        "auto": ("LIVE_LOW", "LIVE_HIGH", "RECORD"),
        "low": ("LIVE_LOW", "LIVE_HIGH", "RECORD"),
        "high": ("LIVE_HIGH", "RECORD", "LIVE_LOW"),
    }
    bindings = {
        binding.purpose: binding
        for binding in camera.stream_bindings
    }
    purpose = next(
        (
            candidate
            for candidate in priorities[quality]
            if candidate in bindings
        ),
        None,
    )
    if purpose is None:
        raise ApiError(
            status_code=409,
            code="camera_live_stream_unavailable",
            message="Camera has no stream bound for live viewing.",
        )

    binding = bindings[purpose]
    profile = next(
        (
            item
            for item in camera.stream_profiles
            if item.id == binding.stream_profile_id
        ),
        None,
    )
    if profile is None:
        raise ApiError(
            status_code=409,
            code="camera_stream_binding_invalid",
            message="Camera live binding references a missing profile.",
        )

    runtime = CameraMediaRuntimeService(request.app.state.settings)
    desired = runtime.desired_streams(session, camera=camera)
    selected = next(
        (
            item
            for item in desired
            if item.profile_id == profile.id
        ),
        None,
    )
    if selected is None:
        raise ApiError(
            status_code=409,
            code="camera_live_stream_unavailable",
            message="Camera live stream is not available.",
        )

    try:
        references = runtime.ensure_streams([selected])
    except ZlmIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc

    reference = references[0]
    hls_url, expires_at = ZlmMediaAccess(
        request.app.state.settings
    ).sign_url(
        runtime.public_hls_url(reference),
        app=reference.app,
        stream=reference.stream,
        ttl_seconds=ZlmMediaAccess.live_ttl_seconds,
    )
    return CameraLiveStreamView(
        camera_id=camera.id,
        profile_id=profile.id,
        purpose=purpose,
        hls_url=hls_url,
        expires_at=expires_at,
        codec=profile.codec,
        width=profile.width,
        height=profile.height,
        fps=profile.fps,
        has_audio=profile.has_audio,
    )
