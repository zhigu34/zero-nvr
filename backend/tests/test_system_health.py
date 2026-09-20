from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.modules.system.health as health_module
from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.storage.models import StorageTarget
from app.modules.system.health import (
    HealthComponent,
    SystemHealthService,
    write_worker_heartbeat,
)


PASSWORD = "correct-horse-battery-staple"


class FakeZlm:
    def __init__(self, _settings, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def version(self):
        return {
            "version": "1.0-test",
            "commit": None,
        }


def make_app(tmp_path: Path):
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    settings = Settings(
        secret_key="system-health-test-secret-key-32-bytes",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'health.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=recordings,
        session_cookie_secure=False,
        zlm_api_secret=SecretStr("zlm-secret-value"),
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def setup_admin(client: TestClient) -> None:
    created = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": PASSWORD,
        },
    )
    assert created.status_code == 201
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": PASSWORD},
    ).status_code == 200


def test_product_health_aggregates_runtime_without_db_health_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    monkeypatch.setattr(
        health_module,
        "ZlmAdapter",
        FakeZlm,
    )

    with app.state.database.session() as session:
        session.add(
            StorageTarget(
                name="Local Recording",
                type="local",
                role="recording",
                enabled=True,
                config_json={
                    "path": str(
                        app.state.settings.recordings_dir
                    )
                },
            )
        )
        session.commit()

    write_worker_heartbeat(
        app.state.settings
    )

    with TestClient(app) as client:
        setup_admin(client)
        response = client.get(
            "/api/v1/system/health"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "DEGRADED"
        assert (
            body["components"]["recording_reconciliation"]["status"]
            == "DEGRADED"
        )
        assert (
            body["components"]["recording_reconciliation"]["message"]
            == "recording_reconciliation_pending"
        )
        assert body["components"]["database"]["status"] == "OK"
        assert body["components"]["worker"]["status"] == "OK"
        assert body["components"]["zlmediakit"]["status"] == "OK"
        assert body["components"]["storage"]["status"] == "OK"
        assert body["components"]["frigate"]["status"] == "DISABLED"
        assert body["components"]["archive"]["status"] == "DISABLED"

        client.post("/api/v1/auth/logout")
        denied = client.get(
            "/api/v1/system/health"
        )
        assert denied.status_code == 401

        assert client.get("/health").status_code == 200



def test_health_surfaces_recording_reconciliation_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from datetime import UTC, datetime

    from app.modules.system.models import SystemSetting

    app = make_app(tmp_path)
    settings = app.state.settings
    database = app.state.database
    try:
        monkeypatch.setattr(
            SystemHealthService,
            "_zlm",
            lambda self: HealthComponent(
                status="OK"
            ),
        )
        monkeypatch.setattr(
            SystemHealthService,
            "_worker",
            lambda self: HealthComponent(
                status="OK"
            ),
        )
        monkeypatch.setattr(
            SystemHealthService,
            "_local_storage",
            staticmethod(
                lambda targets: HealthComponent(
                    status="OK"
                )
            ),
        )

        with database.session() as session:
            session.add(
                SystemSetting(
                    namespace=(
                        "recording.reconciliation"
                    ),
                    value_json={
                        "last_completed_at": (
                            datetime.now(UTC)
                            .isoformat()
                        ),
                        "last_full_at": None,
                        "last_result": {
                            "full": False,
                            "scanned_files": 2,
                            "recovered": 1,
                            "relinked": 0,
                            "missing": 0,
                            "ambiguous": 0,
                            "errors": 0,
                            "skipped_unsettled": 0,
                        },
                    },
                )
            )
            session.commit()

        health = SystemHealthService(
            settings,
            database,
        ).collect()
        component = health.components[
            "recording_reconciliation"
        ]
        assert component.status == "OK"
        assert (
            component.details["recovered"]
            == 1
        )

        with database.session() as session:
            state = session.get(
                SystemSetting,
                "recording.reconciliation",
            )
            assert state is not None
            state.value_json = {
                **state.value_json,
                "last_result": {
                    **state.value_json[
                        "last_result"
                    ],
                    "ambiguous": 1,
                },
            }
            session.commit()

        degraded = SystemHealthService(
            settings,
            database,
        ).collect()
        component = degraded.components[
            "recording_reconciliation"
        ]
        assert component.status == "DEGRADED"
        assert (
            component.message
            == "recording_media_ambiguous"
        )
    finally:
        database.close()
