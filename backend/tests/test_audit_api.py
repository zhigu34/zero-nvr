from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.cameras.models import Camera


PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="audit-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'audit.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def setup_admin(client: TestClient) -> uuid.UUID:
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
    return uuid.UUID(created.json()["id"])


def test_audit_query_redacts_sensitive_fields_and_respects_scope(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        admin_id = setup_admin(client)

        with app.state.database.session() as session:
            visible = Camera(
                name="Visible",
                channel_key="visible",
                enabled=True,
            )
            hidden = Camera(
                name="Hidden",
                channel_key="hidden",
                enabled=True,
            )
            session.add_all([visible, hidden])
            session.flush()
            visible_id = visible.id
            hidden_id = hidden.id

            session.add_all(
                [
                    AuditEvent(
                        actor_type="system",
                        action="global.change",
                        resource_type="system",
                        result="success",
                        before_json={
                            "password": "should-never-leak",
                        },
                    ),
                    AuditEvent(
                        actor_type="system",
                        action="camera.change",
                        resource_type="camera",
                        camera_id=visible_id,
                        result="success",
                        after_json={
                            "nested": {
                                "api_token": "secret-token"
                            }
                        },
                    ),
                    AuditEvent(
                        actor_type="system",
                        action="camera.change",
                        resource_type="camera",
                        camera_id=hidden_id,
                        result="success",
                    ),
                ]
            )
            session.commit()

        with app.state.database.session() as session:
            stored_global = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "global.change"
                )
            )
            assert stored_global is not None
            assert (
                stored_global.before_json["password"]
                == "***"
            )
            stored_camera = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.camera_id == visible_id
                )
            )
            assert stored_camera is not None
            assert (
                stored_camera.after_json["nested"]["api_token"]
                == "***"
            )

        scoped = client.put(
            f"/api/v1/users/{admin_id}/camera-scope",
            json={
                "mode": "selected",
                "camera_ids": [str(visible_id)],
            },
        )
        assert scoped.status_code == 200

        response = client.get(
            "/api/v1/audit?limit=100"
        )
        assert response.status_code == 200
        items = response.json()["items"]
        actions = [item["action"] for item in items]
        assert "global.change" in actions
        assert "camera.change" in actions
        assert not any(
            item["camera_id"] == str(hidden_id)
            for item in items
        )

        global_item = next(
            item
            for item in items
            if item["action"] == "global.change"
        )
        assert global_item["before"]["password"] == "***"

        camera_item = next(
            item
            for item in items
            if item["camera_id"] == str(visible_id)
            and item["action"] == "camera.change"
        )
        assert (
            camera_item["after"]["nested"]["api_token"]
            == "***"
        )

        hidden_query = client.get(
            f"/api/v1/audit?camera_id={hidden_id}"
        )
        assert hidden_query.status_code == 200
        assert hidden_query.json()["items"] == []
