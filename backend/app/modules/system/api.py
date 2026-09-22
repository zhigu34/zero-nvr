from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.integrations.frigate import (
    FrigateHttpAdapter,
    FrigateIntegrationError,
)
from app.integrations.onvif import (
    OnvifAdapter,
    OnvifIntegrationError,
)
from app.modules.audit.service import append_audit_event
from app.modules.cameras.media_runtime import (
    CameraMediaRuntimeService,
)
from app.modules.recordings.models import RecordingPolicy
from app.modules.recordings.policy import RecordingPolicyService
from app.modules.auth.dependencies import require_permission
from app.modules.auth.service import AuthContext

from .camera_ntp import CameraNtpService
from .config_export import ConfigurationExportService
from .config_import import ConfigurationImportService
from .health import SystemHealthService
from .release_validation import (
    ReleaseValidationReportService,
)
from .release_readiness import ReleaseReadinessService
from .frigate_managed import ManagedFrigateConfigService
from .settings import (
    RuntimeTuningSettings,
    RuntimeTuningSettingsService,
    SystemSettingsService,
)
from .frigate import (
    FrigateCredentials,
    FrigateProviderConfig,
    FrigateProviderSettingsService,
)
from .schemas import (
    CameraClockHealthResultView,
    ConfigurationCredentialRequirementView,
    ConfigurationImportApplyItemView,
    ConfigurationImportApplyRequest,
    ConfigurationImportApplyView,
    ConfigurationImportValidateRequest,
    ConfigurationImportValidationView,
    CameraClockHealthView,
    CameraNtpApplyView,
    CameraNtpDeviceResultView,
    FrigateBackfillQueuedView,
    FrigateBackfillRequest,
    FrigateCameraMapping,
    FrigateProviderPut,
    FrigateProviderTestView,
    FrigateProviderView,
    GeneralSystemSettingsView,
    HealthComponentView,
    ReleaseReadinessCheckView,
    ReleaseReadinessView,
    ReleaseValidationArtifactView,
    ReleaseValidationView,
    RuntimeTuningSettingsView,
    SystemHealthView,
    SystemSettingsPatch,
    SystemSettingsView,
    SystemUpdateInfoView,
)


router = APIRouter()


def _credentials_configured(
    config: FrigateProviderConfig,
) -> bool:
    credentials = config.credentials
    return any(
        (
            credentials.http_bearer_token,
            credentials.http_username,
            credentials.http_password,
            credentials.mqtt_username,
            credentials.mqtt_password,
        )
    )


def _frigate_view(
    config: FrigateProviderConfig,
) -> FrigateProviderView:
    return FrigateProviderView(
        enabled=config.enabled,
        mode=config.mode,
        instance_id=config.instance_id,
        base_url=config.base_url,
        camera_map=[
            FrigateCameraMapping(
                frigate_camera=key,
                camera_id=camera_id,
            )
            for key, camera_id in sorted(
                config.camera_map.items()
            )
        ],
        mqtt_enabled=config.mqtt_enabled,
        mqtt_host=config.mqtt_host,
        mqtt_port=config.mqtt_port,
        mqtt_topic_prefix=config.mqtt_topic_prefix,
        mqtt_tls=config.mqtt_tls,
        credentials_configured=_credentials_configured(
            config
        ),
    )


def _frigate_snapshot(
    config: FrigateProviderConfig | None,
) -> dict[str, object] | None:
    if config is None:
        return None
    return {
        "enabled": config.enabled,
        "mode": config.mode,
        "instance_id": config.instance_id,
        "base_url": config.base_url,
        "camera_map": {
            key: str(camera_id)
            for key, camera_id in sorted(
                config.camera_map.items()
            )
        },
        "mqtt_enabled": config.mqtt_enabled,
        "mqtt_host": config.mqtt_host,
        "mqtt_port": config.mqtt_port,
        "mqtt_topic_prefix": config.mqtt_topic_prefix,
        "mqtt_tls": config.mqtt_tls,
        "credentials_configured": _credentials_configured(
            config
        ),
    }


@router.get(
    "/health",
    response_model=SystemHealthView,
)
def system_health(
    request: Request,
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
) -> SystemHealthView:
    health = SystemHealthService(
        request.app.state.settings,
        request.app.state.database,
        frigate_mqtt_runtime=(
            request.app.state.frigate_mqtt
        ),
    ).collect()
    return SystemHealthView(
        status=health.status,
        components={
            name: HealthComponentView(
                status=component.status,
                message=component.message,
                details=component.details,
            )
            for name, component in health.components.items()
        },
    )


@router.get("/info")
def system_info(
    request: Request,
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "database_backend": (
            request.app.state.database.url.get_backend_name()
        ),
    }



@router.get(
    "/integrations/frigate",
    response_model=FrigateProviderView,
)
def get_frigate_provider(
    request: Request,
    _context: AuthContext = Depends(
        require_permission("integration.manage")
    ),
    session: Session = Depends(get_db_session),
) -> FrigateProviderView:
    config = FrigateProviderSettingsService(
        request.app.state.settings
    ).get(session)
    if config is None:
        raise ApiError(
            status_code=404,
            code="frigate_not_configured",
            message="Frigate integration is not configured.",
        )
    return _frigate_view(config)


@router.put(
    "/integrations/frigate",
    response_model=FrigateProviderView,
)
def put_frigate_provider(
    body: FrigateProviderPut,
    request: Request,
    context: AuthContext = Depends(
        require_permission("integration.manage")
    ),
    session: Session = Depends(get_db_session),
) -> FrigateProviderView:
    service = FrigateProviderSettingsService(
        request.app.state.settings
    )
    before = service.get(session)

    mapping = {
        item.frigate_camera: item.camera_id
        for item in body.camera_map
    }
    if len(mapping) != len(body.camera_map):
        raise ApiError(
            status_code=400,
            code="frigate_camera_mapping_duplicate",
            message="Frigate camera mapping contains duplicate camera keys.",
        )

    credential_action = body.credentials_action
    has_credentials = body.credentials is not None
    if (
        credential_action == "replace"
        and not has_credentials
    ):
        raise ApiError(
            status_code=400,
            code="frigate_credentials_update_invalid",
            message=(
                "Frigate credential replacement "
                "requires credential fields."
            ),
        )
    if (
        credential_action != "replace"
        and has_credentials
    ):
        raise ApiError(
            status_code=400,
            code="frigate_credentials_update_invalid",
            message=(
                "Frigate credential values are only "
                "accepted with action=replace."
            ),
        )

    credentials = None
    if has_credentials:
        assert body.credentials is not None
        values = (
            body.credentials.model_dump(
                exclude_none=True
            )
        )
        if not values:
            raise ApiError(
                status_code=400,
                code="frigate_credentials_update_invalid",
                message=(
                    "Frigate credential replacement "
                    "must contain at least one value."
                ),
            )
        credentials = FrigateCredentials(
            http_bearer_token=(
                body.credentials.http_bearer_token.get_secret_value()
                if body.credentials.http_bearer_token
                is not None
                else None
            ),
            http_username=(
                body.credentials.http_username.get_secret_value()
                if body.credentials.http_username is not None
                else None
            ),
            http_password=(
                body.credentials.http_password.get_secret_value()
                if body.credentials.http_password is not None
                else None
            ),
            mqtt_username=(
                body.credentials.mqtt_username.get_secret_value()
                if body.credentials.mqtt_username is not None
                else None
            ),
            mqtt_password=(
                body.credentials.mqtt_password.get_secret_value()
                if body.credentials.mqtt_password is not None
                else None
            ),
        )

    try:
        config = service.put(
            session,
            enabled=body.enabled,
            mode=body.mode,
            base_url=body.base_url,
            camera_map=mapping,
            mqtt_enabled=body.mqtt_enabled,
            mqtt_host=body.mqtt_host,
            mqtt_port=body.mqtt_port,
            mqtt_topic_prefix=body.mqtt_topic_prefix,
            mqtt_tls=body.mqtt_tls,
            credentials=credentials,
            credentials_action=credential_action,
        )
        managed_plan = None
        if (
            config.enabled
            and config.mode == "managed"
        ):
            managed_plan = (
                ManagedFrigateConfigService(
                    request.app.state.settings
                ).build(
                    session,
                    provider=config,
                )
            )

        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="integration.frigate.update",
            resource_type="integration",
            before=_frigate_snapshot(before),
            after=_frigate_snapshot(config),
            metadata={
                "integration": "frigate",
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    background_errors: list[str] = []
    if managed_plan is not None:
        managed_service = ManagedFrigateConfigService(
            request.app.state.settings
        )
        try:
            managed_service.persist(
                managed_plan
            )
        except Exception:
            background_errors.append(
                "managed_config"
            )

        try:
            CameraMediaRuntimeService(
                request.app.state.settings
            ).ensure_streams(
                list(
                    managed_plan.desired_streams
                )
            )
        except Exception:
            background_errors.append(
                "managed_streams"
            )

    if config.enabled:
        try:
            request.app.state.frigate_tasks.backfill(
                lookback_seconds=600
            )
        except Exception:
            background_errors.append("backfill_queue")

    try:
        request.app.state.frigate_mqtt.reconfigure()
    except Exception:
        background_errors.append("mqtt_runtime")

    if background_errors:
        raise ApiError(
            status_code=503,
            code="frigate_runtime_reconcile_failed",
            message="Frigate settings were saved but one or more runtime integrations could not be reconciled.",
            details={
                "settings_persisted": True,
                "failed": background_errors,
            },
        )

    return _frigate_view(config)


@router.post(
    "/integrations/frigate/test",
    response_model=FrigateProviderTestView,
)
def test_frigate_provider(
    request: Request,
    _context: AuthContext = Depends(
        require_permission("integration.manage")
    ),
    session: Session = Depends(get_db_session),
) -> FrigateProviderTestView:
    config = FrigateProviderSettingsService(
        request.app.state.settings
    ).get(session)
    if config is None:
        raise ApiError(
            status_code=404,
            code="frigate_not_configured",
            message="Frigate integration is not configured.",
        )
    session.commit()

    try:
        with FrigateHttpAdapter(
            base_url=config.base_url,
            bearer_token=(
                config.credentials.http_bearer_token
            ),
            username=config.credentials.http_username,
            password=config.credentials.http_password,
            timeout_seconds=10.0,
        ) as adapter:
            version = adapter.version()
    except FrigateIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
        ) from exc

    return FrigateProviderTestView(
        version=version.version,
    )


@router.post(
    "/integrations/frigate/backfill",
    response_model=FrigateBackfillQueuedView,
)
def queue_frigate_backfill(
    body: FrigateBackfillRequest,
    request: Request,
    _context: AuthContext = Depends(
        require_permission("integration.manage")
    ),
    session: Session = Depends(get_db_session),
) -> FrigateBackfillQueuedView:
    config = FrigateProviderSettingsService(
        request.app.state.settings
    ).get(session)
    if config is None or not config.enabled:
        raise ApiError(
            status_code=409,
            code="frigate_not_enabled",
            message="Frigate integration is not enabled.",
        )
    session.commit()

    try:
        request.app.state.frigate_tasks.backfill(
            lookback_seconds=body.lookback_seconds
        )
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="frigate_backfill_queue_unavailable",
            message="Frigate event recovery could not be queued.",
        ) from exc

    return FrigateBackfillQueuedView(
        lookback_seconds=body.lookback_seconds,
    )












@router.post(
    "/configuration/import/apply",
    response_model=ConfigurationImportApplyView,
)
def apply_configuration_import(
    body: ConfigurationImportApplyRequest,
    request: Request,
    context: AuthContext = Depends(
        require_permission("system.manage")
    ),
    session: Session = Depends(
        get_db_session
    ),
) -> ConfigurationImportApplyView:
    try:
        result = ConfigurationImportService.apply(
            session,
            settings=request.app.state.settings,
            bundle=body.bundle,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action=(
                "system.configuration.import.apply"
            ),
            resource_type=(
                "system_configuration"
            ),
            metadata={
                "format": (
                    "zero-nvr.configuration"
                ),
                "format_version": 1,
                "mode": "merge",
                "applied_count": len(
                    result.applied
                ),
                "skipped_count": len(
                    result.skipped
                ),
                "skipped_reasons": sorted(
                    {
                        item.reason
                        for item in result.skipped
                        if item.reason
                    }
                ),
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    warnings = list(result.warnings)
    runtime_failures: list[str] = []
    for camera_id in (
        result.camera_ids_to_reconcile
    ):
        try:
            request.app.state.recording_tasks.reconcile_runtime(
                camera_id
            )
        except Exception:
            runtime_failures.append(
                str(camera_id)
            )
    if runtime_failures:
        warnings.append(
            (
                "Configuration was committed, but runtime "
                "recording reconciliation could not be queued "
                f"for {len(runtime_failures)} camera(s)."
            )
        )

    def view(
        item,
    ) -> ConfigurationImportApplyItemView:
        return ConfigurationImportApplyItemView(
            section=item.section,
            resource_type=item.resource_type,
            source_id=item.source_id,
            target_id=item.target_id,
            name=item.name,
            action=item.action,
            reason=item.reason,
        )

    return ConfigurationImportApplyView(
        applied_count=len(
            result.applied
        ),
        skipped_count=len(
            result.skipped
        ),
        applied=[
            view(item)
            for item in result.applied
        ],
        skipped=[
            view(item)
            for item in result.skipped
        ],
        warnings=warnings,
    )


@router.post(
    "/configuration/import/validate",
    response_model=ConfigurationImportValidationView,
)
def validate_configuration_import(
    body: ConfigurationImportValidateRequest,
    request: Request,
    context: AuthContext = Depends(
        require_permission("system.manage")
    ),
    session: Session = Depends(
        get_db_session
    ),
) -> ConfigurationImportValidationView:
    result = ConfigurationImportService.validate(
        body.bundle,
        settings=request.app.state.settings,
    )
    try:
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action=(
                "system.configuration.import.validate"
            ),
            resource_type=(
                "system_configuration"
            ),
            metadata={
                "format": (
                    "zero-nvr.configuration"
                ),
                "format_version": 1,
                "section_counts": (
                    result.section_counts
                ),
                "credentials_required": len(
                    result.credentials_required
                ),
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return ConfigurationImportValidationView(
        source_application_version=(
            result.source_application_version
        ),
        section_counts=(
            result.section_counts
        ),
        credentials_required=[
            ConfigurationCredentialRequirementView(
                section=item.section,
                resource_type=(
                    item.resource_type
                ),
                resource_id=(
                    item.resource_id
                ),
                name=item.name,
                credential=item.credential,
            )
            for item
            in result.credentials_required
        ],
        warnings=list(
            result.warnings
        ),
    )


@router.get("/configuration/export")
def export_configuration(
    request: Request,
    context: AuthContext = Depends(
        require_permission("system.manage")
    ),
    session: Session = Depends(
        get_db_session
    ),
) -> Response:
    bundle = ConfigurationExportService.build(
        session,
        settings=request.app.state.settings,
    )
    section_counts = {
        key: (
            len(value)
            if isinstance(value, list)
            else len(value)
            if isinstance(value, dict)
            else 0
        )
        for key, value
        in bundle["sections"].items()
    }
    try:
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="system.configuration.export",
            resource_type="system_configuration",
            metadata={
                "format": bundle["format"],
                "format_version": (
                    bundle["format_version"]
                ),
                "secrets_included": False,
                "section_counts": (
                    section_counts
                ),
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    payload = json.dumps(
        bundle,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                'attachment; filename='
                '"zero-nvr-configuration-v1.json"'
            ),
            "Cache-Control": (
                "no-store, max-age=0"
            ),
        },
    )


def _runtime_tuning_view(
    value: RuntimeTuningSettings,
) -> RuntimeTuningSettingsView:
    return RuntimeTuningSettingsView(
        prebuffer_fragment_seconds=(
            value.prebuffer_fragment_seconds
        ),
        prebuffer_buffer_seconds=(
            value.prebuffer_buffer_seconds
        ),
        turn_credential_ttl_seconds=(
            value.turn_credential_ttl_seconds
        ),
        playback_cache_max_bytes=(
            value.playback_cache_max_bytes
        ),
        playback_cache_ttl_seconds=(
            value.playback_cache_ttl_seconds
        ),
        playback_restore_lock_ttl_seconds=(
            value.playback_restore_lock_ttl_seconds
        ),
        live_transcode_max_derivatives=(
            value.live_transcode_max_derivatives
        ),
        live_transcode_idle_ttl_seconds=(
            value.live_transcode_idle_ttl_seconds
        ),
        live_transcode_lease_ttl_seconds=(
            value.live_transcode_lease_ttl_seconds
        ),
        live_transcode_startup_timeout_seconds=(
            value.live_transcode_startup_timeout_seconds
        ),
        live_transcode_cpu_threads=(
            value.live_transcode_cpu_threads
        ),
        live_transcode_video_bitrate_kbps=(
            value.live_transcode_video_bitrate_kbps
        ),
    )


def _runtime_tuning_snapshot(
    value: RuntimeTuningSettings,
) -> dict[str, object]:
    return {
        "prebuffer_fragment_seconds": (
            value.prebuffer_fragment_seconds
        ),
        "prebuffer_buffer_seconds": (
            value.prebuffer_buffer_seconds
        ),
        "turn_credential_ttl_seconds": (
            value.turn_credential_ttl_seconds
        ),
        "playback_cache_max_bytes": (
            value.playback_cache_max_bytes
        ),
        "playback_cache_ttl_seconds": (
            value.playback_cache_ttl_seconds
        ),
        "playback_restore_lock_ttl_seconds": (
            value.playback_restore_lock_ttl_seconds
        ),
        "live_transcode_max_derivatives": (
            value.live_transcode_max_derivatives
        ),
        "live_transcode_idle_ttl_seconds": (
            value.live_transcode_idle_ttl_seconds
        ),
        "live_transcode_lease_ttl_seconds": (
            value.live_transcode_lease_ttl_seconds
        ),
        "live_transcode_startup_timeout_seconds": (
            value.live_transcode_startup_timeout_seconds
        ),
        "live_transcode_cpu_threads": (
            value.live_transcode_cpu_threads
        ),
        "live_transcode_video_bitrate_kbps": (
            value.live_transcode_video_bitrate_kbps
        ),
    }


@router.get(
    "/settings",
    response_model=SystemSettingsView,
)
def get_system_settings(
    request: Request,
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
    session: Session = Depends(get_db_session),
) -> SystemSettingsView:
    general = SystemSettingsService.get(
        session,
        settings=request.app.state.settings,
    )
    runtime = RuntimeTuningSettingsService.get(
        session,
        settings=request.app.state.settings,
    )
    return SystemSettingsView(
        general=GeneralSystemSettingsView(
            system_name=general.system_name,
            display_timezone=general.display_timezone,
            camera_ntp_servers=list(
                general.camera_ntp_servers
            ),
        ),
        runtime=_runtime_tuning_view(runtime),
    )


@router.patch(
    "/settings",
    response_model=SystemSettingsView,
)
def patch_system_settings(
    body: SystemSettingsPatch,
    request: Request,
    context: AuthContext = Depends(
        require_permission("system.manage")
    ),
    session: Session = Depends(get_db_session),
) -> SystemSettingsView:
    before_general = SystemSettingsService.get(
        session,
        settings=request.app.state.settings,
    )
    before_runtime = RuntimeTuningSettingsService.get(
        session,
        settings=request.app.state.settings,
    )

    try:
        after_general = before_general
        if body.general is not None:
            after_general = SystemSettingsService.update(
                session,
                settings=request.app.state.settings,
                changes=body.general.model_dump(
                    exclude_unset=True
                ),
            )

        after_runtime = before_runtime
        if body.runtime is not None:
            after_runtime = (
                RuntimeTuningSettingsService.update(
                    session,
                    settings=request.app.state.settings,
                    changes=body.runtime.model_dump(
                        exclude_unset=True
                    ),
                )
            )

        prebuffer_reconfigure_ids: list = []
        if (
            before_runtime.prebuffer_fragment_seconds
            != after_runtime.prebuffer_fragment_seconds
        ):
            now = datetime.now(UTC)
            policies = list(
                session.scalars(
                    select(RecordingPolicy).where(
                        RecordingPolicy.enabled.is_(True),
                        RecordingPolicy.event_recording_enabled.is_(True),
                    )
                )
            )
            for policy in policies:
                if not (
                    RecordingPolicyService
                    .baseline_should_record(
                        policy,
                        at=now,
                    )
                ):
                    prebuffer_reconfigure_ids.append(
                        policy.camera_id
                    )

        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="system.settings.update",
            resource_type="system_settings",
            before={
                "general": {
                    "system_name": (
                        before_general.system_name
                    ),
                    "display_timezone": (
                        before_general.display_timezone
                    ),
                    "camera_ntp_servers": list(
                        before_general.camera_ntp_servers
                    ),
                },
                "runtime": _runtime_tuning_snapshot(
                    before_runtime
                ),
            },
            after={
                "general": {
                    "system_name": (
                        after_general.system_name
                    ),
                    "display_timezone": (
                        after_general.display_timezone
                    ),
                    "camera_ntp_servers": list(
                        after_general.camera_ntp_servers
                    ),
                },
                "runtime": _runtime_tuning_snapshot(
                    after_runtime
                ),
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    if prebuffer_reconfigure_ids:
        try:
            for camera_id in prebuffer_reconfigure_ids:
                request.app.state.recording_tasks.reconcile_runtime(
                    camera_id,
                    force_reconfigure=True,
                )
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="recording_task_queue_unavailable",
                message=(
                    "Runtime tuning was saved but prebuffer "
                    "recorders could not be queued for reconfiguration."
                ),
                details={
                    "settings_persisted": True,
                    "camera_count": len(
                        prebuffer_reconfigure_ids
                    ),
                },
            ) from exc

    return SystemSettingsView(
        general=GeneralSystemSettingsView(
            system_name=after_general.system_name,
            display_timezone=(
                after_general.display_timezone
            ),
            camera_ntp_servers=list(
                after_general.camera_ntp_servers
            ),
        ),
        runtime=_runtime_tuning_view(
            after_runtime
        ),
    )


@router.get(
    "/update-info",
    response_model=SystemUpdateInfoView,
)
def system_update_info(
    request: Request,
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
) -> SystemUpdateInfoView:
    return SystemUpdateInfoView(
        current_version=request.app.state.settings.app_version,
    )


@router.get("/events/stream")
async def system_events_stream(
    request: Request,
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
):
    event_bus = request.app.state.event_bus
    queue = await event_bus.subscribe()

    async def generate():
        try:
            yield "event: ready\\ndata: {\\\"refetch\\\":true}\\n\\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=15.0,
                    )
                except TimeoutError:
                    yield ": keepalive\\n\\n"
                    continue
                payload = {
                    "at": event["at"],
                    **event["data"],
                }
                yield (
                    "id: " + str(event["id"]) + "\\n"
                    + "event: " + str(event["type"]) + "\\n"
                    + "data: "
                    + json.dumps(payload, separators=(",", ":"))
                    + "\\n\\n"
                )
        finally:
            await event_bus.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



@router.post(
    "/settings/camera-ntp/apply",
    response_model=CameraNtpApplyView,
)
async def apply_camera_ntp_settings(
    request: Request,
    context: AuthContext = Depends(
        require_permission("system.manage")
    ),
    session: Session = Depends(get_db_session),
) -> CameraNtpApplyView:
    general = SystemSettingsService.get(
        session,
        settings=request.app.state.settings,
    )
    servers = tuple(general.camera_ntp_servers)
    mode = "manual" if servers else "dhcp"
    service = CameraNtpService(
        request.app.state.settings
    )
    devices = service.list_devices(session)

    ready = []
    results: list[CameraNtpDeviceResultView] = []
    for device in devices:
        try:
            ready.append(
                service.target(session, device)
            )
        except ApiError as exc:
            results.append(
                CameraNtpDeviceResultView(
                    device_id=device.id,
                    name=device.name,
                    status="FAILED",
                    error_code=exc.code,
                )
            )
    session.commit()

    async def apply_one(target):
        try:
            await OnvifAdapter(
                request.app.state.settings
            ).configure_ntp(
                host=target.host,
                port=target.port,
                username=target.username,
                password=target.password,
                servers=servers,
            )
            return CameraNtpDeviceResultView(
                device_id=target.device_id,
                name=target.name,
                status="UPDATED",
            )
        except OnvifIntegrationError as exc:
            return CameraNtpDeviceResultView(
                device_id=target.device_id,
                name=target.name,
                status="FAILED",
                error_code=exc.code,
            )
        except Exception:
            return CameraNtpDeviceResultView(
                device_id=target.device_id,
                name=target.name,
                status="FAILED",
                error_code="camera_ntp_apply_failed",
            )

    applied = await asyncio.gather(
        *(apply_one(item) for item in ready)
    )
    results.extend(applied)
    results.sort(
        key=lambda item: (
            item.name.lower(),
            str(item.device_id),
        )
    )
    updated = sum(
        item.status == "UPDATED"
        for item in results
    )
    failed = len(results) - updated

    append_audit_event(
        session,
        request=request,
        actor_id=context.user.id,
        action="system.camera_ntp.apply",
        resource_type="system_settings",
        metadata={
            "mode": mode,
            "server_count": len(servers),
            "total_devices": len(devices),
            "updated": updated,
            "failed": failed,
        },
    )
    session.commit()

    return CameraNtpApplyView(
        mode=mode,
        total_devices=len(devices),
        updated=updated,
        failed=failed,
        results=results,
    )



@router.get(
    "/camera-clock-health",
    response_model=CameraClockHealthView,
)
async def camera_clock_health(
    request: Request,
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
    session: Session = Depends(get_db_session),
) -> CameraClockHealthView:
    service = CameraNtpService(
        request.app.state.settings
    )
    devices = service.list_devices(session)
    ready = []
    results: list[CameraClockHealthResultView] = []

    for device in devices:
        try:
            ready.append(
                service.target(session, device)
            )
        except ApiError as exc:
            results.append(
                CameraClockHealthResultView(
                    device_id=device.id,
                    name=device.name,
                    status="ERROR",
                    error_code=exc.code,
                )
            )
    session.commit()

    async def inspect_one(target):
        try:
            reading = await OnvifAdapter(
                request.app.state.settings
            ).read_system_clock(
                host=target.host,
                port=target.port,
                username=target.username,
                password=target.password,
            )
            offset_ms = int(round(reading.offset_ms))
            rtt_ms = int(round(reading.rtt_ms))
            absolute_offset = abs(offset_ms)

            if absolute_offset > 10_000 or rtt_ms > 5_000:
                status = "ERROR"
            elif absolute_offset > 2_000 or rtt_ms > 2_000:
                status = "DEGRADED"
            else:
                status = "OK"

            return CameraClockHealthResultView(
                device_id=target.device_id,
                name=target.name,
                status=status,
                date_time_type=reading.date_time_type,
                timezone=reading.timezone,
                camera_utc_at=reading.utc_datetime,
                offset_ms=offset_ms,
                rtt_ms=rtt_ms,
            )
        except OnvifIntegrationError as exc:
            return CameraClockHealthResultView(
                device_id=target.device_id,
                name=target.name,
                status="ERROR",
                error_code=exc.code,
            )
        except Exception:
            return CameraClockHealthResultView(
                device_id=target.device_id,
                name=target.name,
                status="ERROR",
                error_code="camera_clock_check_failed",
            )

    results.extend(
        await asyncio.gather(
            *(inspect_one(item) for item in ready)
        )
    )
    results.sort(
        key=lambda item: (
            item.name.lower(),
            str(item.device_id),
        )
    )

    ok = sum(item.status == "OK" for item in results)
    degraded = sum(
        item.status == "DEGRADED"
        for item in results
    )
    errors = sum(
        item.status == "ERROR"
        for item in results
    )
    if not results:
        overall = "DISABLED"
    elif errors:
        overall = "ERROR"
    elif degraded:
        overall = "DEGRADED"
    else:
        overall = "OK"

    return CameraClockHealthView(
        status=overall,
        checked_at=datetime.now(UTC),
        total_devices=len(devices),
        ok=ok,
        degraded=degraded,
        error=errors,
        results=results,
    )



@router.get(
    "/release-validation",
    response_model=ReleaseValidationView,
)
def release_validation(
    request: Request,
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
) -> ReleaseValidationView:
    benchmark, soak = (
        ReleaseValidationReportService(
            request.app.state.settings
        ).collect()
    )

    def view(item) -> ReleaseValidationArtifactView:
        return ReleaseValidationArtifactView(
            kind=item.kind,
            state=item.state,
            command=item.command,
            updated_at=item.updated_at,
            report=item.report,
            error_code=item.error_code,
        )

    return ReleaseValidationView(
        benchmark=view(benchmark),
        soak=view(soak),
    )


@router.get(
    "/release-readiness",
    response_model=ReleaseReadinessView,
)
def release_readiness(
    request: Request,
    expected_cameras: int = 8,
    max_age_hours: int = 168,
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
) -> ReleaseReadinessView:
    try:
        result = ReleaseReadinessService(
            request.app.state.settings,
            request.app.state.database,
        ).collect(
            expected_cameras=expected_cameras,
            max_age_hours=max_age_hours,
        )
    except ValueError as exc:
        raise ApiError(
            status_code=400,
            code="release_readiness_invalid_query",
            message=str(exc),
        ) from exc

    return ReleaseReadinessView(
        expected_cameras=result.expected_cameras,
        checked_at=result.checked_at,
        max_age_hours=result.max_age_hours,
        passed=result.passed,
        checks=[
            ReleaseReadinessCheckView(
                name=item.name,
                passed=item.passed,
                code=item.code,
                details=item.details,
            )
            for item in result.checks
        ],
    )
