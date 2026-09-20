from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.v1 import router as api_v1_router
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import install_error_handlers
from app.core.events import RuntimeEventBus
from app.core.logging import configure_logging
from app.integrations.frigate import FrigateMqttRuntime
from app.integrations.zlm import ZlmContinuityTracker
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
    zlm_continuity = ZlmContinuityTracker()
    recorder_modes = RecorderModeTracker()
    prebuffer_fragments = PrebufferFragmentTracker()
    recording_tasks = RecordingTaskDispatcher(resolved_settings)
    backup_tasks = BackupTaskDispatcher()
    export_tasks = ExportTaskDispatcher()
    notification_tasks = NotificationTaskDispatcher()
    storage_tasks = StorageTaskDispatcher()
    frigate_tasks = FrigateTaskDispatcher()
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
        database.close()
        logger.info("zero-nvr API stopped")

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )

    app.state.settings = resolved_settings
    app.state.event_bus = event_bus
    app.state.database = database
    app.state.logger = logger
    app.state.zlm_continuity = zlm_continuity
    app.state.recorder_modes = recorder_modes
    app.state.prebuffer_fragments = prebuffer_fragments
    app.state.recording_tasks = recording_tasks
    app.state.backup_tasks = backup_tasks
    app.state.export_tasks = export_tasks
    app.state.notification_tasks = notification_tasks
    app.state.storage_tasks = storage_tasks
    app.state.frigate_tasks = frigate_tasks
    app.state.frigate_mqtt = frigate_mqtt

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "").strip()
        request_id = incoming[:128] if incoming else str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        if (
            request.method
            in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path.startswith("/api/v1/")
            and response.status_code < 400
        ):
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

    app.include_router(api_v1_router)
    app.include_router(internal_router)
    install_error_handlers(app)
    return app


app = create_app()
