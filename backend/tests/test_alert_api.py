from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.alerts.models import Alert
from app.modules.auth.models import Role
from app.modules.cameras.service import CameraService
from app.modules.events.models import Event


ADMIN_PASSWORD = "correct-horse-battery-staple"
OPERATOR_PASSWORD = "operator-correct-horse-battery"
VIEWER_PASSWORD = "viewer-correct-horse-battery"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="alert-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'alert-api.db'}",
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
            "password": ADMIN_PASSWORD,
        },
    )
    assert created.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": ADMIN_PASSWORD,
        },
    )
    assert login.status_code == 200


def seed_camera_alert(app) -> tuple[str, str]:
    with app.state.database.session() as session:
        camera = CameraService(
            app.state.settings
        ).create_manual_rtsp_camera(
            session,
            name="Front Door",
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url="rtsp://camera.local/main",
            secondary_name=None,
            secondary_url=None,
        )
        event = Event(
            source="system",
            category="test",
            camera_id=camera.id,
            started_at=datetime.now(UTC),
            metadata_json={},
        )
        session.add(event)
        session.flush()
        alert = Alert(
            policy_id=None,
            event_id=event.id,
            camera_id=camera.id,
            severity="warning",
            title="Test alert",
            message="Body",
            state="OPEN",
        )
        session.add(alert)
        session.commit()
        return str(camera.id), str(alert.id)


def role_id(app, name: str) -> str:
    with app.state.database.session() as session:
        role = session.scalar(
            select(Role).where(Role.name == name)
        )
        assert role is not None
        return str(role.id)


def test_notification_target_and_policy_management_hide_secrets(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id, _alert_id = seed_camera_alert(app)

        target = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "Ops",
                "config": {"notify_type": "warning"},
                "url": "json://user:top-secret@example.invalid/token",
            },
        )
        assert target.status_code == 201
        target_body = target.json()
        assert target_body["url_configured"] is True
        rendered = target.text
        assert "top-secret" not in rendered
        assert "example.invalid" not in rendered
        assert "json://" not in rendered

        policy = client.post(
            "/api/v1/alert-policies",
            json={
                "name": "Front person",
                "severity": "warning",
                "match": {
                    "camera_ids": [camera_id],
                    "sources": ["system"],
                    "labels": ["person"],
                    "min_confidence": 0.7,
                },
                "actions": {
                    "notification_target_ids": [
                        target_body["id"]
                    ],
                    "protect_recording": True,
                    "protect_before_seconds": 10,
                    "protect_after_seconds": 20,
                },
                "cooldown_seconds": 60,
            },
        )
        assert policy.status_code == 201
        assert policy.json()["match"]["camera_ids"] == [
            camera_id
        ]
        assert policy.json()["match"]["sources"] == [
            "system"
        ]

        invalid = client.post(
            "/api/v1/alert-policies",
            json={
                "name": "Bad DSL",
                "match": {
                    "python_expression": "event.label == 'person'"
                },
            },
        )
        assert invalid.status_code == 400
        assert (
            invalid.json()["error"]["code"]
            == "alert_policy_match_invalid"
        )

        delete_in_use = client.delete(
            f"/api/v1/notification-targets/{target_body['id']}"
        )
        assert delete_in_use.status_code == 409
        assert (
            delete_in_use.json()["error"]["code"]
            == "notification_target_in_policy"
        )


def test_alert_scope_and_acknowledge_permissions(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id, alert_id = seed_camera_alert(app)

        operator = client.post(
            "/api/v1/users",
            json={
                "username": "operator",
                "display_name": "Operator",
                "password": OPERATOR_PASSWORD,
                "role_ids": [role_id(app, "Operator")],
            },
        )
        assert operator.status_code == 201
        operator_id = operator.json()["id"]

        viewer = client.post(
            "/api/v1/users",
            json={
                "username": "viewer",
                "display_name": "Viewer",
                "password": VIEWER_PASSWORD,
                "role_ids": [role_id(app, "Viewer")],
            },
        )
        assert viewer.status_code == 201
        viewer_id = viewer.json()["id"]

        # Viewer gets explicit selected camera scope and can see the alert.
        selected = client.put(
            f"/api/v1/users/{viewer_id}/camera-scope",
            json={
                "mode": "selected",
                "camera_ids": [camera_id],
            },
        )
        assert selected.status_code == 200

        client.post("/api/v1/auth/logout")
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "viewer",
                "password": VIEWER_PASSWORD,
            },
        ).status_code == 200

        listed = client.get("/api/v1/alerts")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [
            alert_id
        ]

        denied = client.post(
            f"/api/v1/alerts/{alert_id}/acknowledge"
        )
        assert denied.status_code == 403

        client.post("/api/v1/auth/logout")
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "operator",
                "password": OPERATOR_PASSWORD,
            },
        ).status_code == 200

        acknowledged = client.post(
            f"/api/v1/alerts/{alert_id}/acknowledge"
        )
        assert acknowledged.status_code == 200
        assert acknowledged.json()["state"] == "ACKNOWLEDGED"
        assert acknowledged.json()["acknowledged_by"] == operator_id



def test_password_reset_notification_target_requires_safe_mail_target(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        invalid = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "Unsafe reset",
                "config": {
                    "password_reset": True,
                },
                "url": "json://example.invalid/hook",
            },
        )
        assert invalid.status_code == 400
        assert (
            invalid.json()["error"]["code"]
            == "password_reset_target_invalid"
        )

        first = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "Security email",
                "config": {
                    "password_reset": True,
                },
                "url": (
                    "mailtos://smtp-user:smtp-pass@mail.example.com"
                    "?from=zero-nvr@example.com&to=old@example.com"
                ),
            },
        )
        assert first.status_code == 201
        assert (
            first.json()["config"]["password_reset"]
            is True
        )

        conflict = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "Second reset email",
                "config": {
                    "password_reset": True,
                },
                "url": "mailto://localhost?from=zero@example.com",
            },
        )
        assert conflict.status_code == 409
        assert (
            conflict.json()["error"]["code"]
            == "password_reset_target_conflict"
        )
