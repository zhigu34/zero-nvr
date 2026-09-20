from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.cameras.service import CameraService
from app.modules.exports.models import ExportJob


PASSWORD = "correct-horse-battery-staple"


class FakeExportDispatcher:
    def __init__(self) -> None:
        self.ids: list[uuid.UUID] = []

    def render(self, export_id: uuid.UUID) -> None:
        self.ids.append(export_id)

    def expire(self) -> None:
        return None


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="export-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'export-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    app.state.export_tasks = FakeExportDispatcher()
    return app


def setup_admin(client: TestClient) -> uuid.UUID:
    response = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    admin_id = uuid.UUID(response.json()["id"])

    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200
    return admin_id


def seed_camera(app, name: str) -> uuid.UUID:
    with app.state.database.session() as session:
        camera = CameraService(
            app.state.settings
        ).create_manual_rtsp_camera(
            session,
            name=name,
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url=f"rtsp://{name}.local/main",
            secondary_name=None,
            secondary_url=None,
        )
        session.commit()
        return camera.id


def payload(camera_id: uuid.UUID) -> dict[str, object]:
    return {
        "camera_id": str(camera_id),
        "start_at": "2026-09-20T00:00:00Z",
        "end_at": "2026-09-20T00:05:00Z",
        "format": "mp4",
        "codec_mode": "auto",
        "gap_policy": "skip",
    }


def test_export_create_is_idempotent_and_download_path_is_hidden(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera(app, "front-door")

        first = client.post(
            "/api/v1/exports",
            headers={"Idempotency-Key": "clip-1"},
            json=payload(camera_id),
        )
        assert first.status_code == 201
        first_body = first.json()
        export_id = uuid.UUID(first_body["id"])
        assert "output_path" not in first_body

        retry = client.post(
            "/api/v1/exports",
            headers={"Idempotency-Key": "clip-1"},
            json=payload(camera_id),
        )
        assert retry.status_code == 201
        assert retry.json()["id"] == first_body["id"]
        assert app.state.export_tasks.ids == [export_id]

        changed = payload(camera_id)
        changed["end_at"] = "2026-09-20T00:06:00Z"
        conflict = client.post(
            "/api/v1/exports",
            headers={"Idempotency-Key": "clip-1"},
            json=changed,
        )
        assert conflict.status_code == 409
        assert (
            conflict.json()["error"]["code"]
            == "idempotency_key_conflict"
        )

        listed = client.get("/api/v1/exports")
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 1

        detail = client.get(f"/api/v1/exports/{export_id}")
        assert detail.status_code == 200
        assert detail.json()["camera_id"] == str(camera_id)

        output = (
            app.state.settings.cache_dir
            / "exports"
            / f"{export_id}.mp4"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video-data")
        with app.state.database.session() as session:
            job = session.get(ExportJob, export_id)
            assert job is not None
            job.state = "COMPLETED"
            job.output_path = str(output)
            job.size_bytes = output.stat().st_size
            job.actual_duration_ms = 300_000
            job.completed_at = datetime.now(UTC)
            session.commit()

        download = client.get(
            f"/api/v1/exports/{export_id}/download"
        )
        assert download.status_code == 200
        assert download.content == b"video-data"

        deleted = client.delete(
            f"/api/v1/exports/{export_id}"
        )
        assert deleted.status_code == 204
        assert not output.exists()

        after = client.get(f"/api/v1/exports/{export_id}")
        assert after.status_code == 200
        assert after.json()["state"] == "CANCELLED"


def test_export_respects_camera_scope(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        admin_id = setup_admin(client)
        visible = seed_camera(app, "visible")
        hidden = seed_camera(app, "hidden")

        scoped = client.put(
            f"/api/v1/users/{admin_id}/camera-scope",
            json={
                "mode": "selected",
                "camera_ids": [str(visible)],
            },
        )
        assert scoped.status_code == 200

        allowed = client.post(
            "/api/v1/exports",
            json=payload(visible),
        )
        assert allowed.status_code == 201

        denied = client.post(
            "/api/v1/exports",
            json=payload(hidden),
        )
        assert denied.status_code == 404
        assert denied.json()["error"]["code"] == "camera_not_found"

        listed = client.get("/api/v1/exports")
        assert listed.status_code == 200
        assert {
            item["camera_id"]
            for item in listed.json()["items"]
        } == {str(visible)}


def test_export_download_rejects_outside_cache_path(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        camera_id = seed_camera(app, "front")
        created = client.post(
            "/api/v1/exports",
            json=payload(camera_id),
        )
        export_id = uuid.UUID(created.json()["id"])

        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"secret")
        with app.state.database.session() as session:
            job = session.get(ExportJob, export_id)
            assert job is not None
            job.state = "COMPLETED"
            job.output_path = str(outside)
            job.completed_at = datetime.now(UTC)
            session.commit()

        response = client.get(
            f"/api/v1/exports/{export_id}/download"
        )
        assert response.status_code == 409
        assert (
            response.json()["error"]["code"]
            == "export_output_missing"
        )
