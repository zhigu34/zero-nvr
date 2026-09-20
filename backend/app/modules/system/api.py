from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel


router = APIRouter()


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
