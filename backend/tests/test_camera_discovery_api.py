from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.modules.cameras.api as camera_api
from app.core.config import Settings
from app.core.db import Base
from app.integrations.onvif import (
    OnvifDiscoveryCandidate,
    OnvifIntegrationError,
)
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.cameras.models import (
    Camera,
    DiscoveryCandidate,
    DiscoverySession,
)


PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="camera-discovery-test-secret-key-32-bytes",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'camera-discovery.db'}",
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


def test_onvif_discovery_commits_running_session_before_network_and_persists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    observed_source_addresses: list[tuple[str, ...]] = []

    class FakeOnvifAdapter:
        def __init__(self, _settings) -> None:
            pass

        async def discover(
            self,
            *,
            source_addresses: tuple[str, ...] = (),
        ):
            observed_source_addresses.append(source_addresses)
            # The discovery session must be visible from another SQLAlchemy
            # session before any network scan starts. This proves the request
            # is not holding the initial write transaction across network I/O.
            with app.state.database.session() as session:
                running = list(
                    session.scalars(
                        select(DiscoverySession).where(
                            DiscoverySession.status == "running"
                        )
                    )
                )
                assert len(running) == 1
                assert running[0].completed_at is None
                assert running[0].candidates == []

            return [
                OnvifDiscoveryCandidate(
                    candidate_key="urn:uuid:front-door",
                    epr="urn:uuid:front-door",
                    xaddrs=(
                        "http://192.168.50.20:8080/onvif/device_service",
                    ),
                    scopes=(
                        "onvif://www.onvif.org/name/Front%20Door",
                        "onvif://www.onvif.org/location/Entrance",
                    ),
                    host="192.168.50.20",
                    port=8080,
                    device_service_url=(
                        "http://192.168.50.20:8080/onvif/device_service"
                    ),
                ),
                OnvifDiscoveryCandidate(
                    candidate_key="urn:uuid:garage",
                    epr="urn:uuid:garage",
                    xaddrs=(
                        "https://camera-garage.local/onvif/device_service",
                    ),
                    scopes=(
                        "onvif://www.onvif.org/name/Garage",
                    ),
                    host="camera-garage.local",
                    port=443,
                    device_service_url=(
                        "https://camera-garage.local/onvif/device_service"
                    ),
                ),
            ]

    monkeypatch.setattr(camera_api, "OnvifAdapter", FakeOnvifAdapter)

    with TestClient(app) as client:
        setup_admin(client)

        response = client.post(
            "/api/v1/cameras/discovery",
            params={"source_address": "192.168.50.10"},
        )
        assert response.status_code == 201
        assert observed_source_addresses == [("192.168.50.10",)]
        body = response.json()
        assert body["method"] == "onvif_ws_discovery"
        assert body["status"] == "completed"
        assert body["completed_at"] is not None
        assert [item["candidate_key"] for item in body["candidates"]] == [
            "urn:uuid:front-door",
            "urn:uuid:garage",
        ]

        front = body["candidates"][0]
        assert front["host"] == "192.168.50.20"
        assert front["port"] == 8080
        assert front["device_service_url"] == (
            "http://192.168.50.20:8080/onvif/device_service"
        )
        assert front["display_info"]["name"] == "Front Door"
        assert front["display_info"]["location"] == "Entrance"

        discovery_id = body["id"]
        fetched = client.get(
            f"/api/v1/cameras/discovery/{discovery_id}"
        )
        assert fetched.status_code == 200
        assert fetched.json() == body

    with app.state.database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(Camera)
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(DiscoverySession)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(DiscoveryCandidate)
        ) == 2

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "camera.discovery.run"
            )
        )
        assert audit is not None
        assert audit.result == "success"
        assert audit.metadata_json["candidate_count"] == 2


def test_onvif_discovery_rejects_ineligible_source_address(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        response = client.post(
            "/api/v1/cameras/discovery",
            params={"source_address": "127.0.0.1"},
        )

    assert response.status_code == 422
    assert (
        response.json()["error"]["code"]
        == "onvif_discovery_source_address_invalid"
    )
    with app.state.database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(DiscoverySession)
        ) == 0


def test_onvif_discovery_failure_is_persisted_and_sanitized(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    class FailingOnvifAdapter:
        def __init__(self, _settings) -> None:
            pass

        async def discover(
            self,
            *,
            source_addresses: tuple[str, ...] = (),
        ):
            assert source_addresses == ()
            raise OnvifIntegrationError(
                "onvif_discovery_failed",
                "ONVIF device discovery failed.",
                status_code=503,
            )

    monkeypatch.setattr(camera_api, "OnvifAdapter", FailingOnvifAdapter)

    with TestClient(app) as client:
        setup_admin(client)

        response = client.post("/api/v1/cameras/discovery")
        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "onvif_discovery_failed"
        discovery_id = uuid.UUID(
            body["error"]["details"]["discovery_id"]
        )

        fetched = client.get(
            f"/api/v1/cameras/discovery/{discovery_id}"
        )
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "failed"
        assert fetched.json()["candidates"] == []

    with app.state.database.session() as session:
        discovery = session.get(DiscoverySession, discovery_id)
        assert discovery is not None
        assert discovery.status == "failed"
        assert discovery.completed_at is not None

        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "camera.discovery.run"
                )
            )
        )
        assert len(audits) == 1
        assert audits[0].result == "failure"
        assert audits[0].reason == "onvif_discovery_failed"
