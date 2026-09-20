from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.integrations.frigate import (
    FrigateHttpAdapter,
    FrigateIntegrationError,
)
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import require_permission
from app.modules.auth.service import AuthContext

from .settings import SystemSettingsService
from .frigate import (
    FrigateCredentials,
    FrigateProviderConfig,
    FrigateProviderSettingsService,
)
from .schemas import (
    FrigateBackfillQueuedView,
    FrigateBackfillRequest,
    FrigateCameraMapping,
    FrigateProviderPut,
    FrigateProviderTestView,
    FrigateProviderView,
    GeneralSystemSettingsView,
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


class HealthResponse(BaseModel):
    status: str
    database: str
    database_backend: str
    version: str


@router.get("/health", response_model=HealthResponse)
def system_health(request: Request) -> HealthResponse:
    database = request.app.state.database
    settings = request.app.state.settings

    try:
        database.ping()
    except Exception:
        request.app.state.logger.exception("database health check failed")
        return HealthResponse(
            status="error",
            database="error",
            database_backend=database.url.get_backend_name(),
            version=settings.app_version,
        )

    return HealthResponse(
        status="ok",
        database="ok",
        database_backend=database.url.get_backend_name(),
        version=settings.app_version,
    )


@router.get("/info")
def system_info(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
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

    credentials = None
    if body.credentials is not None:
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
            replace_credentials=(
                body.replace_credentials
                or body.credentials is not None
            ),
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
    return SystemSettingsView(
        general=GeneralSystemSettingsView(
            system_name=general.system_name,
            display_timezone=general.display_timezone,
            camera_ntp_servers=list(
                general.camera_ntp_servers
            ),
        )
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
    before = SystemSettingsService.get(
        session,
        settings=request.app.state.settings,
    )
    changes: dict[str, object] = {}
    if body.general is not None:
        changes = body.general.model_dump(
            exclude_unset=True
        )

    try:
        after = SystemSettingsService.update(
            session,
            settings=request.app.state.settings,
            changes=changes,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="system.settings.update",
            resource_type="system_settings",
            before={
                "general": {
                    "system_name": before.system_name,
                    "display_timezone": before.display_timezone,
                    "camera_ntp_servers": list(
                        before.camera_ntp_servers
                    ),
                }
            },
            after={
                "general": {
                    "system_name": after.system_name,
                    "display_timezone": after.display_timezone,
                    "camera_ntp_servers": list(
                        after.camera_ntp_servers
                    ),
                }
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return SystemSettingsView(
        general=GeneralSystemSettingsView(
            system_name=after.system_name,
            display_timezone=after.display_timezone,
            camera_ntp_servers=list(
                after.camera_ntp_servers
            ),
        )
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
