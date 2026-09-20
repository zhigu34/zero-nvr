from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ApiError
from app.main import create_app


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="x" * 32,
        app_version="test-version",
        environment="test",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
    )
    app = create_app(settings)

    @app.get("/test/api-error")
    def test_api_error() -> None:
        raise ApiError(
            status_code=409,
            code="test_conflict",
            message="Test conflict.",
            details={"field": "value"},
        )

    return app


def test_health_info_and_request_id(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/system/health",
            headers={"x-request-id": "known-request-id"},
        )
        assert response.status_code == 200
        assert response.headers["x-request-id"] == "known-request-id"
        assert response.json() == {
            "status": "ok",
            "database": "ok",
            "database_backend": "sqlite",
            "version": "test-version",
        }

        info = client.get("/api/v1/system/info")
        assert info.status_code == 200
        assert info.json() == {
            "name": "zero-nvr",
            "version": "test-version",
            "environment": "test",
        }

        live = client.get("/health")
        assert live.status_code == 200
        assert live.json() == {"status": "ok"}


def test_generated_request_id(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["x-request-id"]


def test_api_error_contract(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/test/api-error",
            headers={"x-request-id": "error-request"},
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "test_conflict",
            "message": "Test conflict.",
            "details": {"field": "value"},
            "request_id": "error-request",
        }
    }
