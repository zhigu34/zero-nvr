from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.v1 import router as api_v1_router
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.integrations.zlm import ZlmContinuityTracker


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    logger = configure_logging(resolved_settings.log_level)
    database = Database(resolved_settings)
    zlm_continuity = ZlmContinuityTracker()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.ensure_runtime_directories()
        database.initialize_runtime()
        database.ping()

        logger.info(
            "zero-nvr API starting",
            extra={
                "version": resolved_settings.app_version,
                "database_backend": database.url.get_backend_name(),
            },
        )

        yield

        database.close()
        logger.info("zero-nvr API stopped")

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )

    app.state.settings = resolved_settings
    app.state.database = database
    app.state.logger = logger
    app.state.zlm_continuity = zlm_continuity

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "").strip()
        request_id = incoming[:128] if incoming else str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/health")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_v1_router)
    install_error_handlers(app)
    return app


app = create_app()
