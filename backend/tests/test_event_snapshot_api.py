from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.modules.events.api as events_api
from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.cameras.service import CameraService
from app.modules.events.models import Event
from app.modules.system.frigate import (
    FrigateCredentials,
    FrigateProviderConfig,
)


ADMIN_PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="event-snapshot-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'events.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def test_event_snapshot_is_proxied_without_exposing_provider_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    provider = FrigateProviderConfig(
        enabled=True,
        mode="external",
        instance_id="frigate-a",
        base_url="http://frigate.internal:5000",
        camera_map={},
        mqtt_enabled=False,
        mqtt_host=None,
        mqtt_port=1883,
        mqtt_topic_prefix="frigate",
        mqtt_tls=False,
        credentials=FrigateCredentials(
            http_bearer_token="provider-secret",
        ),
    )

    monkeypatch.setattr(
        events_api.FrigateProviderSettingsService,
        "get",
        lambda self, session: provider,
    )

    class FakeAdapter:
        def __init__(self, **kwargs):
            assert kwargs["bearer_token"] == "provider-secret"

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def snapshot(self, event_id: str):
            assert event_id == "provider-event-1"
            return b"fake-image", "image/jpeg"

    monkeypatch.setattr(
        events_api,
        "FrigateHttpAdapter",
        FakeAdapter,
    )

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 201
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200

        with app.state.database.session() as session:
            camera = CameraService(
                app.state.settings
            ).create_manual_rtsp_camera(
                session,
                name="Front Door",
                location="Entrance",
                storage_label=None,
                primary_name="Main",
                primary_url="rtsp://camera.local/main",
                secondary_name=None,
                secondary_url=None,
            )
            event = Event(
                source="frigate",
                source_instance_id="frigate-a",
                source_event_id="provider-event-1",
                camera_id=camera.id,
                category="object",
                label="person",
                started_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
                confidence=0.91,
                snapshot_ref=(
                    "frigate://frigate-a/event/provider-event-1/snapshot"
                ),
                metadata_json={"has_snapshot": True},
            )
            session.add(event)
            session.commit()
            event_id = event.id

        response = client.get(
            f"/api/v1/events/{event_id}/snapshot"
        )
        assert response.status_code == 200
        assert response.content == b"fake-image"
        assert response.headers["content-type"].startswith("image/jpeg")
        assert "provider-secret" not in response.text
