from __future__ import annotations

import ipaddress
from dataclasses import dataclass
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from itsdangerous import BadData, URLSafeTimedSerializer
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
    ZlmMediaAccess,
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
from app.modules.recordings.triggers import RecordingTriggerService
from app.modules.system.settings import (
    RuntimeTuningSettingsService,
)

from .discovery_service import CameraDiscoveryService
from .groups import CameraGroupService
from .live_transcode import LiveTranscodeError
from .turn import (
    TurnConfigurationError,
    TurnCredentialService,
)
from .media_runtime import CameraMediaRuntimeService, ZlmStreamReference
from .onvif_onboarding import OnvifOnboardingService
from .ptz import CameraPtzService
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
    CameraGroupCreate,
    CameraGroupUpdate,
    CameraGroupView,
    CameraIceServerView,
    CameraIceServersView,
    CameraLiveStreamView,
    CameraProbeResult,
    CameraProbeStreamView,
    CameraPtzActionView,
    CameraPtzMove,
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
    ptz_capable = False
    if camera.device_id is not None:
        device = session.get(Device, camera.device_id)
        if device is not None:
            adapter_type = device.adapter_type
            ptz_capable = (
                camera.retired_at is None
                and CameraPtzService.is_capable(
                    session,
                    camera,
                )
            )

    return CameraSummary(
        id=camera.id,
        name=camera.name,
        enabled=camera.enabled,
        retired_at=camera.retired_at,
        location=camera.location,
        storage_label=camera.storage_label,
        adapter_type=adapter_type,
        ptz_capable=ptz_capable,
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
        "retired_at": (
            summary.retired_at.isoformat()
            if summary.retired_at is not None
            else None
        ),
        "location": summary.location,
        "storage_label": summary.storage_label,
        "adapter_type": summary.adapter_type,
    }


def _camera_group_view(
    session: Session,
    group,
) -> CameraGroupView:
    return CameraGroupView(
        id=group.id,
        name=group.name,
        description=group.description,
        parent_id=group.parent_id,
        camera_ids=CameraGroupService.camera_ids(
            session,
            group.id,
        ),
    )


def _camera_group_snapshot(
    session: Session,
    group,
) -> dict[str, object]:
    view = _camera_group_view(session, group)
    return {
        "name": view.name,
        "description": view.description,
        "parent_id": (
            str(view.parent_id)
            if view.parent_id is not None
            else None
        ),
        "camera_ids": sorted(
            str(item) for item in view.camera_ids
        ),
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


@router.get(
    "/camera-groups",
    response_model=list[CameraGroupView],
)
def list_camera_groups(
    _context: AuthContext = Depends(
        require_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> list[CameraGroupView]:
    return [
        _camera_group_view(session, group)
        for group in CameraGroupService.list(session)
    ]


@router.post(
    "/camera-groups",
    response_model=CameraGroupView,
    status_code=201,
)
def create_camera_group(
    body: CameraGroupCreate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> CameraGroupView:
    try:
        group = CameraGroupService.create(
            session,
            name=body.name,
            description=body.description,
            parent_id=body.parent_id,
            camera_ids=body.camera_ids,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="camera_group.create",
            resource_type="camera_group",
            resource_id=group.id,
            after=_camera_group_snapshot(
                session,
                group,
            ),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _camera_group_view(session, group)


@router.get(
    "/camera-groups/{group_id}",
    response_model=CameraGroupView,
)
def get_camera_group(
    group_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> CameraGroupView:
    return _camera_group_view(
        session,
        CameraGroupService.get(session, group_id),
    )


@router.patch(
    "/camera-groups/{group_id}",
    response_model=CameraGroupView,
)
def update_camera_group(
    group_id: uuid.UUID,
    body: CameraGroupUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> CameraGroupView:
    group = CameraGroupService.get(session, group_id)
    before = _camera_group_snapshot(session, group)
    try:
        group = CameraGroupService.update(
            session,
            group=group,
            changes=body.model_dump(exclude_unset=True),
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="camera_group.update",
            resource_type="camera_group",
            resource_id=group.id,
            before=before,
            after=_camera_group_snapshot(
                session,
                group,
            ),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _camera_group_view(session, group)


@router.delete(
    "/camera-groups/{group_id}",
    status_code=204,
)
def delete_camera_group(
    group_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    group = CameraGroupService.get(session, group_id)
    before = _camera_group_snapshot(session, group)
    resource_id = group.id
    try:
        CameraGroupService.delete(
            session,
            group=group,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="camera_group.delete",
            resource_type="camera_group",
            resource_id=resource_id,
            before=before,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return Response(status_code=204)


@router.get("/cameras", response_model=list[CameraSummary])
def list_cameras(
    include_retired: bool = Query(default=False),
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
            include_retired=include_retired,
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
        device, cameras, reconfigured = service.import_device(
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
            action=(
                "camera.onvif.reconfigure"
                if reconfigured
                else "camera.onvif.import"
            ),
            resource_type="device",
            resource_id=device.id,
            metadata={
                "camera_ids": [str(camera.id) for camera in cameras],
                "camera_count": len(cameras),
                "profile_count": sum(
                    len(camera.stream_profiles)
                    for camera in cameras
                ),
                "reconfigured": reconfigured,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    if reconfigured:
        try:
            for camera in cameras:
                request.app.state.recording_tasks.reconcile_runtime(
                    camera.id,
                    restart_streams=True,
                )
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="camera_runtime_queue_unavailable",
                message=(
                    "ONVIF device configuration was saved but "
                    "runtime reconciliation could not be queued."
                ),
                details={
                    "device_id": str(device.id),
                    "configuration_persisted": True,
                },
            ) from exc

    return OnvifImportResult(
        device_id=device.id,
        reconfigured=reconfigured,
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

    try:
        request.app.state.recording_tasks.reconcile_runtime(
            camera_id
        )
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="camera_runtime_queue_unavailable",
            message=(
                "Camera state was saved but runtime reconciliation "
                "could not be queued."
            ),
            details={
                "camera_persisted": True,
                "camera_id": str(camera_id),
                "enabled": enabled,
            },
        ) from exc

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



def _set_camera_retired(
    *,
    camera_id: uuid.UUID,
    retired: bool,
    request: Request,
    context: AuthContext,
    session: Session,
) -> CameraDetail:
    closed_manual_triggers = 0
    try:
        camera = CameraService.get_camera(session, camera_id)
        before = _camera_audit_snapshot(session, camera)
        camera = CameraService.set_retired(
            session,
            camera=camera,
            retired=retired,
        )
        if retired:
            closed_manual_triggers = (
                RecordingTriggerService.close_active_manual_for_camera(
                    session,
                    camera_id=camera.id,
                )
            )
        after = _camera_audit_snapshot(session, camera)
        if before != after:
            append_audit_event(
                session,
                request=request,
                actor_id=context.user.id,
                action=(
                    "camera.retire"
                    if retired
                    else "camera.restore"
                ),
                resource_type="camera",
                resource_id=camera.id,
                camera_id=camera.id,
                before=before,
                after=after,
                metadata={
                    "closed_manual_recording_triggers": (
                        closed_manual_triggers
                    )
                },
            )
        session.commit()
    except Exception:
        session.rollback()
        raise

    if retired:
        try:
            request.app.state.recording_tasks.reconcile_runtime(
                camera_id
            )
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="camera_runtime_queue_unavailable",
                message=(
                    "Camera was retired but runtime reconciliation "
                    "could not be queued."
                ),
                details={
                    "camera_persisted": True,
                    "camera_id": str(camera_id),
                    "retired": True,
                },
            ) from exc

    return _camera_detail(session, camera)


@router.post(
    "/cameras/{camera_id}/retire",
    response_model=CameraDetail,
)
def retire_camera(
    camera_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> CameraDetail:
    return _set_camera_retired(
        camera_id=camera_id,
        retired=True,
        request=request,
        context=context,
        session=session,
    )


@router.post(
    "/cameras/{camera_id}/restore",
    response_model=CameraDetail,
)
def restore_camera(
    camera_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("camera.configure")
    ),
    session: Session = Depends(get_db_session),
) -> CameraDetail:
    return _set_camera_retired(
        camera_id=camera_id,
        retired=False,
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



LivePurpose = Literal["LIVE_HIGH", "LIVE_LOW", "RECORD"]


@dataclass(frozen=True, slots=True)
class _LiveSelection:
    camera: Camera
    profile: CameraStreamProfile
    purpose: LivePurpose
    runtime: CameraMediaRuntimeService
    reference: ZlmStreamReference


def _select_live_stream(
    *,
    camera_id: uuid.UUID,
    quality: Literal["auto", "high", "low"],
    request: Request,
    session: Session,
) -> _LiveSelection:
    camera = CameraService.get_camera(
        session,
        camera_id,
    )
    if not camera.enabled:
        raise ApiError(
            status_code=409,
            code="camera_disabled",
            message="Camera is disabled.",
        )

    priorities: dict[
        str,
        tuple[LivePurpose, ...],
    ] = {
        "auto": (
            "LIVE_LOW",
            "LIVE_HIGH",
            "RECORD",
        ),
        "low": (
            "LIVE_LOW",
            "LIVE_HIGH",
            "RECORD",
        ),
        "high": (
            "LIVE_HIGH",
            "RECORD",
            "LIVE_LOW",
        ),
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
            message=(
                "Camera has no stream bound "
                "for live viewing."
            ),
        )

    binding = bindings[purpose]
    profile = next(
        (
            item
            for item in camera.stream_profiles
            if item.id
            == binding.stream_profile_id
        ),
        None,
    )
    if profile is None:
        raise ApiError(
            status_code=409,
            code="camera_stream_binding_invalid",
            message=(
                "Camera live binding references "
                "a missing profile."
            ),
        )

    runtime = CameraMediaRuntimeService(
        request.app.state.settings
    )
    desired = runtime.desired_streams(
        session,
        camera=camera,
    )
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
            message=(
                "Camera live stream is not "
                "available."
            ),
        )

    try:
        references = runtime.ensure_streams(
            [selected]
        )
    except ZlmIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc

    return _LiveSelection(
        camera=camera,
        profile=profile,
        purpose=purpose,
        runtime=runtime,
        reference=references[0],
    )


def _whep_ticket_serializer(
    request: Request,
) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        request.app.state.settings.secret_key
        .get_secret_value(),
        salt="zero-nvr-whep-session-v1",
    )


def _whep_cleanup_ticket(
    request: Request,
    *,
    camera_id: uuid.UUID,
    user_id: uuid.UUID,
    media_session_id: uuid.UUID,
    session_id: str,
    session_token: str,
) -> str:
    return _whep_ticket_serializer(
        request
    ).dumps(
        {
            "camera_id": str(camera_id),
            "user_id": str(user_id),
            "media_session_id": str(
                media_session_id
            ),
            "session_id": session_id,
            "session_token": session_token,
        }
    )


def _parse_whep_cleanup_ticket(
    request: Request,
    *,
    ticket: str,
    camera_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[str, str, uuid.UUID]:
    try:
        payload = _whep_ticket_serializer(
            request
        ).loads(
            ticket,
            max_age=60 * 60,
        )
    except BadData as exc:
        raise ApiError(
            status_code=404,
            code="camera_whep_session_not_found",
            message=(
                "WebRTC live session was not "
                "found or has expired."
            ),
        ) from exc

    if not isinstance(payload, dict):
        raise ApiError(
            status_code=404,
            code="camera_whep_session_not_found",
            message=(
                "WebRTC live session was not "
                "found or has expired."
            ),
        )

    if (
        payload.get("camera_id")
        != str(camera_id)
        or payload.get("user_id")
        != str(user_id)
    ):
        raise ApiError(
            status_code=404,
            code="camera_whep_session_not_found",
            message=(
                "WebRTC live session was not "
                "found or has expired."
            ),
        )

    session_id = payload.get("session_id")
    session_token = payload.get(
        "session_token"
    )
    raw_media_session_id = payload.get(
        "media_session_id"
    )
    try:
        media_session_id = uuid.UUID(
            str(raw_media_session_id)
        )
    except (TypeError, ValueError) as exc:
        raise ApiError(
            status_code=404,
            code="camera_whep_session_not_found",
            message=(
                "WebRTC live session was not "
                "found or has expired."
            ),
        ) from exc
    if (
        not isinstance(session_id, str)
        or not session_id
        or not isinstance(session_token, str)
        or not session_token
    ):
        raise ApiError(
            status_code=404,
            code="camera_whep_session_not_found",
            message=(
                "WebRTC live session was not "
                "found or has expired."
            ),
        )
    return (
        session_id,
        session_token,
        media_session_id,
    )


def _whep_candidate_udp(
    request: Request,
) -> str | None:
    settings = request.app.state.settings
    host = settings.zlm_webrtc_extern_ip
    if host is None:
        request_host = request.url.hostname
        if not request_host:
            return None
        try:
            address = ipaddress.ip_address(
                request_host
            )
        except ValueError:
            return None
        if address.version != 4:
            return None
        host = str(address)
    else:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return None
        if address.version != 4:
            return None
        host = str(address)

    return (
        f"{host}:"
        f"{settings.zlm_webrtc_port}"
    )


def _require_live_media_session(
    request: Request,
    *,
    media_session_id: uuid.UUID,
    camera_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    if request.app.state.media_sessions.authorize(
        media_session_id,
        owner_user_id=user_id,
        camera_id=camera_id,
    ):
        return
    raise ApiError(
        status_code=404,
        code="media_session_not_found",
        message=(
            "Live media session was not found "
            "or has expired."
        ),
    )


@router.get(
    "/cameras/{camera_id}/live",
    response_model=CameraLiveStreamView,
)
def get_camera_live_stream(
    camera_id: uuid.UUID,
    request: Request,
    quality: Literal[
        "auto",
        "high",
        "low",
    ] = Query(default="auto"),
    context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(
        get_db_session
    ),
) -> CameraLiveStreamView:
    selection = _select_live_stream(
        camera_id=camera_id,
        quality=quality,
        request=request,
        session=session,
    )
    media_session_id = (
        request.app.state.media_sessions.issue(
            owner_user_id=context.user.id,
            camera_id=selection.camera.id,
            ttl_seconds=(
                ZlmMediaAccess.live_ttl_seconds
            ),
        )
    )
    try:
        hls_url, expires_at = ZlmMediaAccess(
            request.app.state.settings
        ).sign_url(
            selection.runtime.public_hls_url(
                selection.reference
            ),
            app=selection.reference.app,
            stream=selection.reference.stream,
            ttl_seconds=(
                ZlmMediaAccess.live_ttl_seconds
            ),
            session_id=media_session_id,
        )
    except Exception:
        request.app.state.media_sessions.revoke(
            media_session_id
        )
        raise

    return CameraLiveStreamView(
        camera_id=selection.camera.id,
        profile_id=selection.profile.id,
        purpose=selection.purpose,
        hls_url=hls_url,
        media_session_id=media_session_id,
        expires_at=expires_at,
        codec=selection.profile.codec,
        width=selection.profile.width,
        height=selection.profile.height,
        fps=selection.profile.fps,
        has_audio=selection.profile.has_audio,
    )


@router.get(
    "/cameras/{camera_id}/live/ice",
    response_model=CameraIceServersView,
)
def get_camera_live_ice_servers(
    camera_id: uuid.UUID,
    request: Request,
    response: Response,
    media_session_id: uuid.UUID = Query(),
    context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> CameraIceServersView:
    _require_live_media_session(
        request,
        media_session_id=media_session_id,
        camera_id=camera_id,
        user_id=context.user.id,
    )
    response.headers[
        "Cache-Control"
    ] = "private, no-store"
    try:
        runtime_tuning = (
            RuntimeTuningSettingsService.get(
                session,
                settings=request.app.state.settings,
            )
        )
        bundle = TurnCredentialService(
            request.app.state.settings
        ).issue(
            user_id=context.user.id,
            request_host=(
                request.url.hostname
            ),
            credential_ttl_seconds=(
                runtime_tuning
                .turn_credential_ttl_seconds
            ),
        )
    except TurnConfigurationError as exc:
        raise ApiError(
            status_code=503,
            code="turn_unavailable",
            message=str(exc),
        ) from exc

    if bundle is None:
        return CameraIceServersView(
            enabled=False,
        )

    return CameraIceServersView(
        enabled=True,
        ice_servers=[
            CameraIceServerView(
                urls=bundle.urls,
                username=bundle.username,
                credential=bundle.credential,
                expires_at=bundle.expires_at,
            )
        ],
    )


@router.post(
    "/cameras/{camera_id}/live/whep",
    status_code=201,
)
async def create_camera_whep_session(
    camera_id: uuid.UUID,
    request: Request,
    media_session_id: uuid.UUID = Query(),
    quality: Literal[
        "auto",
        "high",
        "low",
    ] = Query(default="auto"),
    context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(
        get_db_session
    ),
) -> Response:
    _require_live_media_session(
        request,
        media_session_id=media_session_id,
        camera_id=camera_id,
        user_id=context.user.id,
    )
    content_type = request.headers.get(
        "content-type",
        "",
    ).split(";", 1)[0].strip().lower()
    if content_type != "application/sdp":
        raise ApiError(
            status_code=415,
            code="camera_whep_content_type_invalid",
            message=(
                "WebRTC negotiation requires "
                "application/sdp."
            ),
        )

    offer_bytes = await request.body()
    if (
        not offer_bytes
        or len(offer_bytes) > 256 * 1024
    ):
        raise ApiError(
            status_code=422,
            code="camera_whep_offer_invalid",
            message="WebRTC offer SDP is invalid.",
        )
    try:
        offer_sdp = offer_bytes.decode(
            "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise ApiError(
            status_code=422,
            code="camera_whep_offer_invalid",
            message="WebRTC offer SDP is invalid.",
        ) from exc

    selection = _select_live_stream(
        camera_id=camera_id,
        quality=quality,
        request=request,
        session=session,
    )
    access = ZlmMediaAccess(
        request.app.state.settings
    )
    playback_params, _expires_at = (
        access.issue_params(
            app=selection.reference.app,
            stream=selection.reference.stream,
            ttl_seconds=(
                ZlmMediaAccess.live_ttl_seconds
            ),
            session_id=media_session_id,
        )
    )

    try:
        with ZlmAdapter(
            request.app.state.settings
        ) as zlm:
            whep = zlm.whep_play(
                app=selection.reference.app,
                stream=selection.reference.stream,
                offer_sdp=offer_sdp,
                playback_params=(
                    playback_params
                ),
                candidate_udp=(
                    _whep_candidate_udp(
                        request
                    )
                ),
                candidate_tcp=(
                    _whep_candidate_udp(
                        request
                    )
                ),
            )
    except ZlmIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc

    cleanup_key = f"whep:{whep.session_id}"
    cleanup_settings = (
        request.app.state.settings
    )

    def cleanup_whep() -> None:
        try:
            with ZlmAdapter(
                cleanup_settings
            ) as cleanup_zlm:
                cleanup_zlm.delete_webrtc(
                    session_id=whep.session_id,
                    session_token=whep.session_token,
                )
        except ZlmIntegrationError:
            pass

    if not request.app.state.media_sessions.register_cleanup(
        media_session_id,
        key=cleanup_key,
        cleanup=cleanup_whep,
    ):
        cleanup_whep()
        raise ApiError(
            status_code=404,
            code="media_session_not_found",
            message=(
                "Live media session was not "
                "found or has expired."
            ),
        )

    ticket = _whep_cleanup_ticket(
        request,
        camera_id=camera_id,
        user_id=context.user.id,
        media_session_id=media_session_id,
        session_id=whep.session_id,
        session_token=whep.session_token,
    )
    location = (
        f"/api/v1/cameras/{camera_id}"
        f"/live/whep/{ticket}"
    )
    return Response(
        content=whep.answer_sdp,
        status_code=201,
        media_type="application/sdp",
        headers={
            "Location": location,
            "Cache-Control": "no-store",
        },
    )


@router.delete(
    "/cameras/{camera_id}/live/whep/{ticket}",
    status_code=204,
)
def delete_camera_whep_session(
    camera_id: uuid.UUID,
    ticket: str,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
) -> Response:
    (
        session_id,
        session_token,
        media_session_id,
    ) = (
        _parse_whep_cleanup_ticket(
            request,
            ticket=ticket,
            camera_id=camera_id,
            user_id=context.user.id,
        )
    )
    try:
        with ZlmAdapter(
            request.app.state.settings
        ) as zlm:
            zlm.delete_webrtc(
                session_id=session_id,
                session_token=session_token,
            )
    except ZlmIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc
    request.app.state.media_sessions.unregister_cleanup(
        media_session_id,
        key=f"whep:{session_id}",
    )
    return Response(status_code=204)


@router.post(
    "/cameras/{camera_id}/live/compatibility",
    response_model=CameraLiveStreamView,
    status_code=201,
)
def create_camera_live_compatibility(
    camera_id: uuid.UUID,
    request: Request,
    media_session_id: uuid.UUID = Query(),
    quality: Literal[
        "auto",
        "high",
        "low",
    ] = Query(default="auto"),
    context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(
        get_db_session
    ),
) -> CameraLiveStreamView:
    _require_live_media_session(
        request,
        media_session_id=media_session_id,
        camera_id=camera_id,
        user_id=context.user.id,
    )
    selection = _select_live_stream(
        camera_id=camera_id,
        quality=quality,
        request=request,
        session=session,
    )
    access = ZlmMediaAccess(
        request.app.state.settings
    )
    source_url, _source_expires_at = (
        access.sign_url(
            selection.runtime.internal_rtsp_url(
                selection.reference
            ),
            app=selection.reference.app,
            stream=selection.reference.stream,
            ttl_seconds=(
                ZlmMediaAccess.live_ttl_seconds
            ),
            session_id=media_session_id,
        )
    )
    try:
        lease = request.app.state.live_transcodes.acquire(
            camera_id=selection.camera.id,
            owner_user_id=context.user.id,
            profile_id=selection.profile.id,
            source_url=source_url,
            has_audio=selection.profile.has_audio,
        )
    except LiveTranscodeError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc

    cleanup_key = (
        f"compat:{lease.lease_id}"
    )
    live_transcodes = (
        request.app.state.live_transcodes
    )

    def cleanup_compat() -> None:
        live_transcodes.release(
            lease.lease_id,
            camera_id=selection.camera.id,
            owner_user_id=context.user.id,
        )

    if not request.app.state.media_sessions.register_cleanup(
        media_session_id,
        key=cleanup_key,
        cleanup=cleanup_compat,
    ):
        cleanup_compat()
        raise ApiError(
            status_code=404,
            code="media_session_not_found",
            message=(
                "Live media session was not "
                "found or has expired."
            ),
        )

    try:
        hls_url, expires_at = access.sign_url(
            selection.runtime.public_hls_url(
                lease.reference
            ),
            app=lease.reference.app,
            stream=lease.reference.stream,
            ttl_seconds=(
                ZlmMediaAccess.live_ttl_seconds
            ),
            session_id=media_session_id,
        )
    except Exception:
        request.app.state.media_sessions.unregister_cleanup(
            media_session_id,
            key=cleanup_key,
        )
        cleanup_compat()
        raise

    return CameraLiveStreamView(
        camera_id=selection.camera.id,
        profile_id=selection.profile.id,
        purpose=selection.purpose,
        transports=["hls"],
        hls_url=hls_url,
        media_session_id=media_session_id,
        expires_at=expires_at,
        codec="h264",
        width=selection.profile.width,
        height=selection.profile.height,
        fps=selection.profile.fps,
        has_audio=selection.profile.has_audio,
        compatibility="h264_transcode",
        compatibility_lease_id=lease.lease_id,
        compatibility_acceleration=(
            lease.acceleration
        ),
    )


@router.post(
    "/cameras/{camera_id}/live/compatibility/{lease_id}/keepalive",
    status_code=204,
)
def keep_camera_live_compatibility(
    camera_id: uuid.UUID,
    lease_id: uuid.UUID,
    request: Request,
    media_session_id: uuid.UUID = Query(),
    context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
) -> Response:
    _require_live_media_session(
        request,
        media_session_id=media_session_id,
        camera_id=camera_id,
        user_id=context.user.id,
    )
    if not request.app.state.live_transcodes.touch(
        lease_id,
        camera_id=camera_id,
        owner_user_id=context.user.id,
    ):
        raise ApiError(
            status_code=404,
            code="live_transcode_lease_not_found",
            message=(
                "Compatibility transcode lease "
                "was not found."
            ),
        )
    return Response(status_code=204)


@router.delete(
    "/cameras/{camera_id}/live/compatibility/{lease_id}",
    status_code=204,
)
def release_camera_live_compatibility(
    camera_id: uuid.UUID,
    lease_id: uuid.UUID,
    request: Request,
    media_session_id: uuid.UUID = Query(),
    context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
) -> Response:
    _require_live_media_session(
        request,
        media_session_id=media_session_id,
        camera_id=camera_id,
        user_id=context.user.id,
    )
    request.app.state.media_sessions.unregister_cleanup(
        media_session_id,
        key=f"compat:{lease_id}",
    )
    request.app.state.live_transcodes.release(
        lease_id,
        camera_id=camera_id,
        owner_user_id=context.user.id,
    )
    return Response(status_code=204)


@router.delete(
    "/cameras/{camera_id}/live/session/{media_session_id}",
    status_code=204,
)
def revoke_camera_live_session(
    camera_id: uuid.UUID,
    media_session_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
) -> Response:
    request.app.state.media_sessions.revoke(
        media_session_id,
        owner_user_id=context.user.id,
        camera_id=camera_id,
    )
    return Response(status_code=204)


@router.get("/cameras/{camera_id}/snapshot")
def get_camera_snapshot(
    camera_id: uuid.UUID,
    request: Request,
    _context: AuthContext = Depends(
        require_camera_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    camera = CameraService.get_camera(session, camera_id)
    if not camera.enabled:
        raise ApiError(
            status_code=409,
            code="camera_disabled",
            message="Camera is disabled.",
        )

    bindings = {
        binding.purpose: binding
        for binding in camera.stream_bindings
    }
    purpose = next(
        (
            candidate
            for candidate in (
                "SNAPSHOT",
                "LIVE_HIGH",
                "RECORD",
                "LIVE_LOW",
            )
            if candidate in bindings
        ),
        None,
    )
    if purpose is None:
        raise ApiError(
            status_code=409,
            code="camera_snapshot_unavailable",
            message="Camera has no stream bound for snapshots.",
        )

    profile_id = bindings[purpose].stream_profile_id
    runtime = CameraMediaRuntimeService(
        request.app.state.settings
    )
    desired = runtime.desired_streams(
        session,
        camera=camera,
    )
    selected = next(
        (
            item
            for item in desired
            if item.profile_id == profile_id
        ),
        None,
    )
    if selected is None:
        raise ApiError(
            status_code=409,
            code="camera_snapshot_unavailable",
            message="Camera snapshot stream is unavailable.",
        )

    try:
        references = runtime.ensure_streams([selected])
        reference = references[0]
        with ZlmAdapter(
            request.app.state.settings
        ) as zlm:
            content, content_type = zlm.snapshot(
                source_url=runtime.internal_rtsp_url(
                    reference
                ),
                timeout_seconds=10,
                expire_seconds=3,
            )
    except ZlmIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc

    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f'attachment; filename="zero-nvr-{camera.id}-snapshot.jpg"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )



@router.post(
    "/cameras/{camera_id}/ptz/move",
    response_model=CameraPtzActionView,
)
async def move_camera_ptz(
    camera_id: uuid.UUID,
    body: CameraPtzMove,
    request: Request,
    _context: AuthContext = Depends(
        require_camera_permission("camera.control")
    ),
    session: Session = Depends(get_db_session),
) -> CameraPtzActionView:
    if (
        abs(body.pan) < 1e-9
        and abs(body.tilt) < 1e-9
        and abs(body.zoom) < 1e-9
    ):
        raise ApiError(
            status_code=400,
            code="camera_ptz_move_invalid",
            message="PTZ move requires non-zero velocity.",
        )

    camera = CameraService.get_camera(
        session,
        camera_id,
    )
    if not camera.enabled:
        raise ApiError(
            status_code=409,
            code="camera_disabled",
            message="Camera is disabled.",
        )
    connection = CameraPtzService(
        request.app.state.settings
    ).connection(session, camera)
    session.commit()

    try:
        await OnvifAdapter(
            request.app.state.settings
        ).ptz_move(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=connection.password,
            preferred_profile_tokens=(
                connection.preferred_profile_tokens
            ),
            pan=body.pan,
            tilt=body.tilt,
            zoom=body.zoom,
        )
    except OnvifIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc
    return CameraPtzActionView()


@router.post(
    "/cameras/{camera_id}/ptz/stop",
    response_model=CameraPtzActionView,
)
async def stop_camera_ptz(
    camera_id: uuid.UUID,
    request: Request,
    _context: AuthContext = Depends(
        require_camera_permission("camera.control")
    ),
    session: Session = Depends(get_db_session),
) -> CameraPtzActionView:
    camera = CameraService.get_camera(
        session,
        camera_id,
    )
    connection = CameraPtzService(
        request.app.state.settings
    ).connection(session, camera)
    session.commit()

    try:
        await OnvifAdapter(
            request.app.state.settings
        ).ptz_stop(
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password=connection.password,
            preferred_profile_tokens=(
                connection.preferred_profile_tokens
            ),
        )
    except OnvifIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details={},
        ) from exc
    return CameraPtzActionView()
