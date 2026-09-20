from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.system.models import SystemSetting


PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="system-settings-test-secret-key-32-bytes",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'system.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
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
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": PASSWORD},
    )
    assert login.status_code == 200


def test_system_settings_are_bounded_persisted_and_audited(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        defaults = client.get(
            "/api/v1/system/settings"
        )
        assert defaults.status_code == 200
        assert defaults.json()["general"] == {
            "system_name": "zero-nvr",
            "display_timezone": "UTC",
            "camera_ntp_servers": [],
        }

        updated = client.patch(
            "/api/v1/system/settings",
            json={
                "general": {
                    "system_name": "Home NVR",
                    "display_timezone": "America/Los_Angeles",
                    "camera_ntp_servers": [
                        "pool.ntp.org",
                        "192.168.1.1",
                        "POOL.NTP.ORG",
                    ],
                }
            },
        )
        assert updated.status_code == 200
        assert updated.json()["general"] == {
            "system_name": "Home NVR",
            "display_timezone": "America/Los_Angeles",
            "camera_ntp_servers": [
                "pool.ntp.org",
                "192.168.1.1",
            ],
        }

        bad = client.patch(
            "/api/v1/system/settings",
            json={
                "general": {
                    "camera_ntp_servers": [
                        "https://evil.example/ntp"
                    ]
                }
            },
        )
        assert bad.status_code == 400
        assert (
            bad.json()["error"]["code"]
            == "system_ntp_server_invalid"
        )

        update_info = client.get(
            "/api/v1/system/update-info"
        )
        assert update_info.status_code == 200
        assert (
            update_info.json()["deployment_method"]
            == "deploy.sh"
        )
        assert (
            update_info.json()["automatic_host_mutation"]
            is False
        )

    with app.state.database.session() as session:
        row = session.get(
            SystemSetting,
            "general",
        )
        assert row is not None
        assert row.value_json["system_name"] == "Home NVR"
        actions = set(
            session.scalars(
                select(AuditEvent.action)
            ).all()
        )
        assert "system.settings.update" in actions
