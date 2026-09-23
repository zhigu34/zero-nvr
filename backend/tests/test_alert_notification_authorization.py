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
from app.modules.notifications.models import (
    NotificationDelivery,
    NotificationTarget,
)


ADMIN_PASSWORD = "correct-horse-battery-staple"
USER_PASSWORD = "scoped-user-correct-horse-battery"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key=(
            "alert-notification-auth-test-"
            "secret-key-32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'authorization.db'}"
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


def login(
    client: TestClient,
    username: str,
    password: str,
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )
    assert response.status_code == 200


def role_id(
    app,
    name: str,
) -> str:
    with app.state.database.session() as session:
        role = session.scalar(
            select(Role).where(
                Role.name == name
            )
        )
        assert role is not None
        return str(role.id)


def create_user(
    client: TestClient,
    *,
    username: str,
    role_ids: list[str],
) -> str:
    response = client.post(
        "/api/v1/users",
        json={
            "username": username,
            "display_name": username,
            "password": USER_PASSWORD,
            "role_ids": role_ids,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def set_camera_scope(
    client: TestClient,
    *,
    user_id: str,
    camera_id: str,
) -> None:
    response = client.put(
        f"/api/v1/users/{user_id}/camera-scope",
        json={
            "mode": "selected",
            "camera_ids": [camera_id],
        },
    )
    assert response.status_code == 200


def seed_alerts_and_deliveries(
    app,
) -> dict[str, str]:
    with app.state.database.session() as session:
        first = CameraService(
            app.state.settings
        ).create_manual_rtsp_camera(
            session,
            name="Front Door",
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url=(
                "rtsp://front.local/main"
            ),
            secondary_name=None,
            secondary_url=None,
        )
        second = CameraService(
            app.state.settings
        ).create_manual_rtsp_camera(
            session,
            name="Back Door",
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url=(
                "rtsp://back.local/main"
            ),
            secondary_name=None,
            secondary_url=None,
        )

        now = datetime.now(UTC)
        first_event = Event(
            source="system",
            category="source_connectivity",
            label="source_lost",
            camera_id=first.id,
            started_at=now,
            metadata_json={},
        )
        second_event = Event(
            source="system",
            category="source_connectivity",
            label="source_lost",
            camera_id=second.id,
            started_at=now,
            metadata_json={},
        )
        system_event = Event(
            source="system",
            category="storage_health",
            label="storage_critical",
            camera_id=None,
            started_at=now,
            metadata_json={},
        )
        session.add_all(
            [
                first_event,
                second_event,
                system_event,
            ]
        )
        session.flush()

        first_alert = Alert(
            event_id=first_event.id,
            camera_id=first.id,
            severity="warning",
            title="Front source offline",
            state="OPEN",
        )
        second_alert = Alert(
            event_id=second_event.id,
            camera_id=second.id,
            severity="warning",
            title="Back source offline",
            state="OPEN",
        )
        system_alert = Alert(
            event_id=system_event.id,
            camera_id=None,
            severity="critical",
            title="Storage critical",
            state="OPEN",
        )
        session.add_all(
            [
                first_alert,
                second_alert,
                system_alert,
            ]
        )
        session.flush()

        target = NotificationTarget(
            name="Ops",
            kind="apprise",
            enabled=True,
            config_json={},
        )
        session.add(target)
        session.flush()

        first_delivery = NotificationDelivery(
            alert_id=first_alert.id,
            purpose="alert",
            notification_target_id=target.id,
            state="SENT",
            attempt_count=1,
            title="Front alert",
            body="Front source offline",
        )
        second_delivery = NotificationDelivery(
            alert_id=second_alert.id,
            purpose="alert",
            notification_target_id=target.id,
            state="SENT",
            attempt_count=1,
            title="Back alert",
            body="Back source offline",
        )
        system_delivery = NotificationDelivery(
            alert_id=None,
            purpose="security",
            notification_target_id=target.id,
            state="SENT",
            attempt_count=1,
            title="Security notice",
            body="System-wide notice",
        )
        session.add_all(
            [
                first_delivery,
                second_delivery,
                system_delivery,
            ]
        )
        session.commit()

        return {
            "first_camera": str(first.id),
            "second_camera": str(second.id),
            "first_alert": str(first_alert.id),
            "second_alert": str(second_alert.id),
            "system_alert": str(system_alert.id),
            "first_delivery": str(
                first_delivery.id
            ),
            "second_delivery": str(
                second_delivery.id
            ),
            "system_delivery": str(
                system_delivery.id
            ),
        }


def test_alert_and_notification_permissions_are_independent_and_scoped(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 201
        login(
            client,
            "admin",
            ADMIN_PASSWORD,
        )

        seeded = seed_alerts_and_deliveries(
            app
        )

        operator_id = create_user(
            client,
            username="operator",
            role_ids=[
                role_id(
                    app,
                    "Operator",
                )
            ],
        )
        set_camera_scope(
            client,
            user_id=operator_id,
            camera_id=seeded["first_camera"],
        )

        event_only_role = client.post(
            "/api/v1/roles",
            json={
                "name": "Event only",
                "permissions": [
                    "event.view",
                ],
            },
        )
        assert event_only_role.status_code == 201
        event_only_id = create_user(
            client,
            username="event-only",
            role_ids=[
                event_only_role.json()["id"]
            ],
        )
        set_camera_scope(
            client,
            user_id=event_only_id,
            camera_id=seeded["first_camera"],
        )

        alert_only_role = client.post(
            "/api/v1/roles",
            json={
                "name": "Alert only",
                "permissions": [
                    "alert.view",
                ],
            },
        )
        assert alert_only_role.status_code == 201
        alert_only_id = create_user(
            client,
            username="alert-only",
            role_ids=[
                alert_only_role.json()["id"]
            ],
        )
        set_camera_scope(
            client,
            user_id=alert_only_id,
            camera_id=seeded["first_camera"],
        )

        client.post(
            "/api/v1/auth/logout"
        )
        login(
            client,
            "event-only",
            USER_PASSWORD,
        )
        denied_alerts = client.get(
            "/api/v1/alerts"
        )
        assert denied_alerts.status_code == 403
        assert (
            denied_alerts.json()["error"][
                "details"
            ]["permission"]
            == "alert.view"
        )

        client.post(
            "/api/v1/auth/logout"
        )
        login(
            client,
            "alert-only",
            USER_PASSWORD,
        )
        alert_only = client.get(
            "/api/v1/alerts"
        )
        assert alert_only.status_code == 200
        assert {
            item["id"]
            for item in alert_only.json()["items"]
        } == {
            seeded["first_alert"]
        }
        hidden_system = client.get(
            f"/api/v1/alerts/{seeded['system_alert']}"
        )
        assert hidden_system.status_code == 404

        denied_deliveries = client.get(
            "/api/v1/notification-deliveries"
        )
        assert denied_deliveries.status_code == 403
        assert (
            denied_deliveries.json()["error"][
                "details"
            ]["permission"]
            == "notification.view"
        )

        client.post(
            "/api/v1/auth/logout"
        )
        login(
            client,
            "operator",
            USER_PASSWORD,
        )

        alerts = client.get(
            "/api/v1/alerts"
        )
        assert alerts.status_code == 200
        alert_ids = {
            item["id"]
            for item in alerts.json()["items"]
        }
        assert (
            seeded["first_alert"]
            in alert_ids
        )
        assert (
            seeded["second_alert"]
            not in alert_ids
        )
        assert (
            seeded["system_alert"]
            in alert_ids
        )

        deliveries = client.get(
            "/api/v1/notification-deliveries"
        )
        assert deliveries.status_code == 200
        delivery_ids = {
            item["id"]
            for item in deliveries.json()
        }
        assert (
            seeded["first_delivery"]
            in delivery_ids
        )
        assert (
            seeded["second_delivery"]
            not in delivery_ids
        )
        assert (
            seeded["system_delivery"]
            in delivery_ids
        )

        targets = client.get(
            "/api/v1/notification-targets"
        )
        assert targets.status_code == 200

        denied_target_create = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "Denied",
                "url": (
                    "json://example.invalid/hook"
                ),
            },
        )
        assert denied_target_create.status_code == 403
        assert (
            denied_target_create.json()[
                "error"
            ]["details"]["permission"]
            == "notification.manage"
        )

        resolved = client.post(
            f"/api/v1/alerts/{seeded['first_alert']}/resolve"
        )
        assert resolved.status_code == 403
        assert (
            resolved.json()["error"][
                "details"
            ]["permission"]
            == "alert.manage"
        )

        acknowledged = client.post(
            f"/api/v1/alerts/{seeded['first_alert']}/acknowledge"
        )
        assert acknowledged.status_code == 200
        assert (
            acknowledged.json()["state"]
            == "ACKNOWLEDGED"
        )
