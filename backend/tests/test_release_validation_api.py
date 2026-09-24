from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app


PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key=(
            "release-validation-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'validation.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(
        app.state.database.engine
    )
    return app


def setup_admin(client: TestClient) -> None:
    assert client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": PASSWORD,
        },
    ).status_code == 201
    assert client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": PASSWORD,
        },
    ).status_code == 200


def test_release_validation_reports_are_read_only_and_bounded(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    root = (
        app.state.settings.data_dir
        / "release-validation"
    )
    root.mkdir(parents=True)

    (root / "latest-benchmark.json").write_text(
        json.dumps(
            {
                "profile": "8-camera-baseline",
                "passed": True,
                "generated_at": (
                    "2026-09-20T18:00:00+00:00"
                ),
                "resources": {
                    "control_plane_memory_peak_bytes": (
                        128 * 1024 * 1024
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "latest-soak.json").write_text(
        "{not-json",
        encoding="utf-8",
    )

    with TestClient(app) as client:
        denied = client.get(
            "/api/v1/system/release-validation"
        )
        assert denied.status_code == 401

        setup_admin(client)
        response = client.get(
            "/api/v1/system/release-validation"
        )
        assert response.status_code == 200
        body = response.json()

        benchmark = body["benchmark"]
        assert benchmark["state"] == "AVAILABLE"
        assert (
            benchmark["report"]["profile"]
            == "8-camera-baseline"
        )
        assert benchmark["report"]["passed"] is True
        assert benchmark["updated_at"]
        assert (
            benchmark["command"]
            .startswith("./deploy.sh benchmark")
        )

        soak = body["soak"]
        assert soak["state"] == "INVALID"
        assert soak["report"] is None
        assert (
            soak["error_code"]
            == "release_validation_report_invalid"
        )
        assert "tmp" not in json.dumps(body).lower()


def test_release_validation_reports_missing_state(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        response = client.get(
            "/api/v1/system/release-validation"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["benchmark"]["state"] == "MISSING"
        assert body["soak"]["state"] == "MISSING"

def test_release_readiness_api_requires_current_release_gates(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    root = (
        app.state.settings.data_dir
        / "release-validation"
    )
    root.mkdir(parents=True)
    generated_at = datetime.now(UTC).isoformat()

    (root / "latest-benchmark.json").write_text(
        json.dumps(
            {
                "profile": "8-camera-baseline",
                "passed": True,
                "generated_at": generated_at,
            }
        ),
        encoding="utf-8",
    )
    (root / "latest-soak.json").write_text(
        json.dumps(
            {
                "profile": "8-camera-soak",
                "passed": True,
                "generated_at": generated_at,
                "duration_seconds": 3600,
            }
        ),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        denied = client.get(
            "/api/v1/system/release-readiness"
        )
        assert denied.status_code == 401

        setup_admin(client)
        response = client.get(
            "/api/v1/system/release-readiness",
            params={
                "expected_cameras": 8,
                "max_age_hours": 24,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["expected_cameras"] == 8
        assert body["max_age_hours"] == 24
        assert body["passed"] is False

        checks = {
            item["name"]: item
            for item in body["checks"]
        }
        assert checks["benchmark"]["passed"] is True
        assert checks["soak"]["passed"] is True
        assert (
            checks["verified_backup"]["passed"]
            is False
        )
        assert (
            checks["verified_backup"]["code"]
            == "verified_backup_missing"
        )


def test_release_readiness_api_rejects_unknown_camera_target(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        response = client.get(
            "/api/v1/system/release-readiness",
            params={"expected_cameras": 12},
        )
        assert response.status_code == 400
        body = response.json()
        assert (
            body["error"]["code"]
            == "release_readiness_invalid_query"
        )

