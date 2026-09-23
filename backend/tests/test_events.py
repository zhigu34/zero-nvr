from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base
from app.core.errors import ApiError
from app.main import create_app
from app.modules.auth.models import Role
from app.modules.cameras.service import CameraService
from app.modules.events.models import Event
from app.modules.events.service import EventIngest, EventService
from app.modules.recordings.models import RecordingPolicy


ADMIN_PASSWORD = "correct-horse-battery-staple"
VIEWER_PASSWORD = "viewer-correct-horse-battery"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="event-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'events.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=tmp_path / "recordings",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
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


def seed_camera(app, name: str):
    with app.state.database.session() as session:
        camera = CameraService(
            app.state.settings
        ).create_manual_rtsp_camera(
            session,
            name=name,
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url=f"rtsp://{name.lower().replace(' ', '-')}.local/main",
            secondary_name=None,
            secondary_url=None,
        )
        session.add(
            RecordingPolicy(
                camera_id=camera.id,
                baseline_mode="disabled",
                event_recording_enabled=True,
                enabled=True,
            )
        )
        session.commit()
        return camera.id


def ingest(
    app,
    *,
    source_event_id: str | None,
    camera_id: uuid.UUID | None,
    started_at: datetime,
    ended_at: datetime | None = None,
    label: str | None = "person",
    confidence: float | None = 0.9,
    zone: str | None = "porch",
    severity: str | None = "info",
):
    with app.state.database.session() as session:
        result = EventService.upsert_provider_event(
            session,
            item=EventIngest(
                source="frigate",
                source_instance_id=(
                    "frigate-main"
                    if source_event_id is not None
                    else None
                ),
                source_event_id=source_event_id,
                camera_id=camera_id,
                category="object",
                label=label,
                started_at=started_at,
                ended_at=ended_at,
                confidence=confidence,
                severity=severity,
                zone=zone,
                correlation_id=source_event_id,
                metadata={"track": "canonical-only"},
            ),
        )
        session.commit()
        return result.event.id


def test_provider_event_upsert_updates_one_canonical_row(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    camera_id = seed_camera(app, "Front Door")
    start = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

    with app.state.database.session() as session:
        first = EventService.upsert_provider_event(
            session,
            item=EventIngest(
                source="frigate",
                source_instance_id="frigate-main",
                source_event_id="evt-123",
                camera_id=camera_id,
                category="object",
                label="person",
                started_at=start,
                confidence=0.71,
                zone="porch",
                metadata={"phase": "start"},
            ),
        )
        assert first.created is True
        first_id = first.event.id
        session.commit()

    with app.state.database.session() as session:
        second = EventService.upsert_provider_event(
            session,
            item=EventIngest(
                source="frigate",
                source_instance_id="frigate-main",
                source_event_id="evt-123",
                camera_id=camera_id,
                category="object",
                label="person",
                started_at=start,
                ended_at=start + timedelta(seconds=8),
                confidence=0.93,
                severity="warning",
                zone="porch",
                metadata={"phase": "end"},
            ),
        )
        assert second.created is False
        assert second.event.id == first_id
        session.commit()

        assert session.scalar(
            select(func.count()).select_from(Event)
        ) == 1
        row = session.get(Event, first_id)
        assert row is not None
        assert row.ended_at == start + timedelta(seconds=8)
        assert row.confidence == 0.93
        assert row.severity == "warning"
        assert row.metadata_json == {"phase": "end"}


def test_event_metadata_is_redacted_before_persistence(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with app.state.database.session() as session:
        result = EventService.upsert_provider_event(
            session,
            item=EventIngest(
                source="frigate",
                source_instance_id="frigate-main",
                source_event_id="evt-secret-metadata",
                category="object",
                started_at=datetime.now(UTC),
                metadata={
                    "token": "provider-token",
                    "nested": {
                        "message": (
                            "password=provider-password"
                        )
                    },
                },
            ),
        )
        event_id = result.event.id
        session.commit()

    with app.state.database.session() as session:
        stored = session.get(Event, event_id)
        assert stored is not None
        assert stored.metadata_json["token"] == "***"
        assert (
            "provider-password"
            not in stored.metadata_json["nested"]["message"]
        )


def test_provider_identity_requires_instance_when_event_id_exists(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with app.state.database.session() as session:
        try:
            EventService.upsert_provider_event(
                session,
                item=EventIngest(
                    source="frigate",
                    source_instance_id=None,
                    source_event_id="evt-no-instance",
                    category="object",
                    started_at=datetime.now(UTC),
                ),
            )
        except ApiError as exc:
            assert exc.code == "event_source_instance_required"
        else:
            raise AssertionError("missing source instance must be rejected")


def test_event_api_cursor_filters_and_camera_scope(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        front_id = seed_camera(app, "Front Door")
        back_id = seed_camera(app, "Back Door")
        base = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

        front_old = ingest(
            app,
            source_event_id="front-old",
            camera_id=front_id,
            started_at=base,
            confidence=0.75,
        )
        front_new = ingest(
            app,
            source_event_id="front-new",
            camera_id=front_id,
            started_at=base + timedelta(minutes=2),
            confidence=0.95,
        )
        back_event = ingest(
            app,
            source_event_id="back",
            camera_id=back_id,
            started_at=base + timedelta(minutes=1),
            confidence=0.99,
        )
        global_event = ingest(
            app,
            source_event_id=None,
            camera_id=None,
            started_at=base + timedelta(minutes=3),
            label="service",
            zone=None,
            confidence=None,
            severity="warning",
        )

        with app.state.database.session() as session:
            viewer_role = session.scalar(
                select(Role).where(Role.name == "Viewer")
            )
            assert viewer_role is not None
            viewer_role_id = viewer_role.id

        viewer = client.post(
            "/api/v1/users",
            json={
                "username": "viewer",
                "display_name": "Viewer",
                "password": VIEWER_PASSWORD,
                "role_ids": [str(viewer_role_id)],
            },
        )
        assert viewer.status_code == 201
        viewer_id = viewer.json()["id"]

        scope = client.put(
            f"/api/v1/users/{viewer_id}/camera-scope",
            json={
                "mode": "selected",
                "camera_ids": [str(front_id)],
            },
        )
        assert scope.status_code == 200

        client.post("/api/v1/auth/logout")
        login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "viewer",
                "password": VIEWER_PASSWORD,
            },
        )
        assert login.status_code == 200

        page1 = client.get(
            "/api/v1/events",
            params={"limit": 2},
        )
        assert page1.status_code == 200
        body1 = page1.json()
        assert [item["id"] for item in body1["items"]] == [
            str(global_event),
            str(front_new),
        ]
        assert body1["next_cursor"] is not None

        page2 = client.get(
            "/api/v1/events",
            params={
                "limit": 2,
                "cursor": body1["next_cursor"],
            },
        )
        assert page2.status_code == 200
        assert [item["id"] for item in page2.json()["items"]] == [
            str(front_old),
        ]

        filtered = client.get(
            "/api/v1/events",
            params={
                "camera_id": str(front_id),
                "confidence": 0.9,
                "source": "frigate",
                "category": "object",
                "label": "person",
                "zone": "porch",
            },
        )
        assert filtered.status_code == 200
        assert [item["id"] for item in filtered.json()["items"]] == [
            str(front_new),
        ]

        hidden_filter = client.get(
            "/api/v1/events",
            params={"camera_id": str(back_id)},
        )
        assert hidden_filter.status_code == 404

        hidden_detail = client.get(
            f"/api/v1/events/{back_event}"
        )
        assert hidden_detail.status_code == 404
        assert hidden_detail.json()["error"]["code"] == "event_not_found"

        global_detail = client.get(
            f"/api/v1/events/{global_event}"
        )
        assert global_detail.status_code == 200


def test_timeline_overlays_events_that_overlap_requested_window(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera(app, "Front Door")

        event_start = datetime(
            2026,
            9,
            20,
            11,
            59,
            55,
            tzinfo=UTC,
        )
        event_id = ingest(
            app,
            source_event_id="timeline-overlap",
            camera_id=camera_id,
            started_at=event_start,
            ended_at=event_start + timedelta(seconds=15),
        )

        response = client.get(
            f"/api/v1/cameras/{camera_id}/timeline",
            params={
                "from": "2026-09-20T12:00:00Z",
                "to": "2026-09-20T12:01:00Z",
            },
        )
        assert response.status_code == 200
        events = response.json()["events"]
        assert events == [
            {
                "id": str(event_id),
                "marker_type": "range",
                "category": "object",
                "label": "person",
                "start_at": "2026-09-20T11:59:55Z",
                "end_at": "2026-09-20T12:00:10Z",
                "count": 1,
                "category_counts": {
                    "object": 1,
                },
                "label_counts": {
                    "person": 1,
                },
            }
        ]
