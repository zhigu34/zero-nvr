from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1 import router as api_v1_router
from app.core.config import Settings, get_settings
from app.core.db import (
    Database,
    assert_database_schema_current,
)
from app.core.errors import install_error_handlers
from app.core.events import RuntimeEventBus
from app.core.logging import configure_logging
from app.frontend import mount_frontend
from app.integrations.frigate import FrigateMqttRuntime
from app.integrations.onvif import OnvifEventRuntime
from app.integrations.zlm import ZlmContinuityTracker
from app.modules.auth.rate_limit import AuthRateLimiter
from app.modules.cameras.clock_projection import (
    CameraClockProjectionStore,
)
from app.modules.cameras.live_transcode import LiveTranscodeManager
from app.modules.cameras.media_sessions import MediaSessionRegistry
from app.modules.cameras.runtime_reconciler import (
    RuntimeReconciler,
)
from app.modules.backups.dispatcher import BackupTaskDispatcher
from app.modules.notifications.dispatcher import NotificationTaskDispatcher
from app.modules.exports.dispatcher import ExportTaskDispatcher
from app.modules.recordings.dispatcher import RecordingTaskDispatcher
from app.modules.recordings.prebuffer import PrebufferFragmentTracker
from app.modules.recordings.runtime import RecorderModeTracker
from app.modules.storage.dispatcher import StorageTaskDispatcher
from app.modules.system.frigate_dispatcher import FrigateTaskDispatcher
from app.internal import router as internal_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    logger = configure_logging(resolved_settings.log_level)
    database = Database(resolved_settings)
    event_bus = RuntimeEventBus()
    auth_rate_limiter = AuthRateLimiter()
    zlm_continuity = ZlmContinuityTracker()
    recorder_modes = RecorderModeTracker()
    camera_clock_projections = (
        CameraClockProjectionStore()
    )
    prebuffer_fragments = PrebufferFragmentTracker()
    live_transcodes = LiveTranscodeManager(
        resolved_settings,
        database=database,
    )
    media_sessions = MediaSessionRegistry()
    recording_tasks = RecordingTaskDispatcher(
        resolved_settings,
        database=database,
    )
    runtime_reconciler = RuntimeReconciler(
        database,
        reconcile_camera=(
            recording_tasks.reconcile_runtime
        ),
    )
    backup_tasks = BackupTaskDispatcher()
    export_tasks = ExportTaskDispatcher()
    notification_tasks = NotificationTaskDispatcher()
    storage_tasks = StorageTaskDispatcher()
    frigate_tasks = FrigateTaskDispatcher()
    onvif_events = OnvifEventRuntime(
        resolved_settings,
        database,
        logger=logger,
    )
    frigate_mqtt = FrigateMqttRuntime(
        resolved_settings,
        database,
        logger=logger,
        recording_tasks=recording_tasks,
        notification_tasks=notification_tasks,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.ensure_runtime_directories()
        database.initialize_runtime()
        database.ping()
        if (
            resolved_settings.environment.lower()
            != "test"
        ):
            assert_database_schema_current(
                database
            )
            queued = (
                runtime_reconciler.enqueue_all()
            )
            logger.info(
                "runtime reconciliation queued",
                extra={
                    "camera_count": queued,
                },
            )
            onvif_events.start()
        frigate_mqtt.start()

        logger.info(
            "zero-nvr API starting",
            extra={
                "version": resolved_settings.app_version,
                "database_backend": database.url.get_backend_name(),
            },
        )

        yield

        frigate_mqtt.stop()
        onvif_events.stop()
        media_sessions.stop()
        live_transcodes.stop()
        database.close()
        logger.info("zero-nvr API stopped")

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=(
            resolved_settings.secret_key.get_secret_value()
        ),
        session_cookie="zero_nvr_oidc_state",
        max_age=600,
        same_site="lax",
        https_only=(
            resolved_settings.session_cookie_secure
        ),
    )

    app.state.settings = resolved_settings
    app.state.event_bus = event_bus
    app.state.auth_rate_limiter = auth_rate_limiter
    app.state.database = database
    app.state.logger = logger
    app.state.zlm_continuity = zlm_continuity
    app.state.recorder_modes = recorder_modes
    app.state.camera_clock_projections = (
        camera_clock_projections
    )
    app.state.prebuffer_fragments = prebuffer_fragments
    app.state.live_transcodes = live_transcodes
    app.state.media_sessions = media_sessions
    app.state.recording_tasks = recording_tasks
    app.state.runtime_reconciler = runtime_reconciler
    app.state.backup_tasks = backup_tasks
    app.state.export_tasks = export_tasks
    app.state.notification_tasks = notification_tasks
    app.state.storage_tasks = storage_tasks
    app.state.frigate_tasks = frigate_tasks
    app.state.frigate_mqtt = frigate_mqtt
    app.state.onvif_events = onvif_events

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "").strip()
        request_id = incoming[:128] if incoming else str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path.startswith("/api/v1/")
            and response.status_code < 400
        ):
            if request.url.path.startswith(
                "/api/v1/cameras"
            ):
                onvif_events.reconfigure()
            await event_bus.publish(
                "api.mutation",
                {
                    "method": request.method,
                    "path": request.url.path,
                    "request_id": request_id,
                },
            )
        return response

    @app.get("/health")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def readiness():
        try:
            database.ping()
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable"},
            )
        return {"status": "ok"}

    app.include_router(api_v1_router)
    app.include_router(internal_router)
    install_error_handlers(app)
    mount_frontend(app)
    return app


app = create_app()
