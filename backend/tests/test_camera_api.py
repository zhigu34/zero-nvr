from __future__ import annotations

import uuid
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import SecretRecord
from app.modules.cameras.models import (
    Camera,
    CameraStreamProfile,
    DeviceEndpoint,
)
from app.modules.cameras.service import CameraService


COOKIE = "zero_nvr_session"
ADMIN_PASSWORD = "correct-horse-battery-staple"
VIEWER_PASSWORD = "viewer-correct-horse-battery"


class FakeRecordingTasks:
    def __init__(self) -> None:
        self.runtime_reconciles: list[uuid.UUID] = []

    def reconcile_runtime(self, camera_id: uuid.UUID) -> None:
        self.runtime_reconciles.append(camera_id)


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="camera-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'camera-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    app.state.recording_tasks = FakeRecordingTasks()
    return app


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    token = client.cookies.get(COOKIE)
    assert token
    return token


def use_token(client: TestClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(COOKIE, token)


def create_camera(
    client: TestClient,
    *,
    name: str,
    host: str,
    with_secondary: bool = True,
):
    body = {
        "mode": "manual_rtsp",
        "name": name,
        "location": "Lab",
        "primary_stream": {
            "name": "Main",
            "rtsp_url": (
                f"rtsp://alice:super-secret@{host}:8554/live/main"
                "?token=top-secret-token"
            ),
        },
    }
    if with_secondary:
        body["secondary_stream"] = {
            "name": "Sub",
            "rtsp_url": (
                f"rtsp://alice:super-secret@{host}:8554/live/sub"
                "?token=top-secret-token"
            ),
        }

    response = client.post("/api/v1/cameras", json=body)
    assert response.status_code == 201
    return response


def test_manual_rtsp_secret_storage_scope_and_bindings(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": ADMIN_PASSWORD,
            },
        )
        assert setup.status_code == 201
        admin_token = login(client, "admin", ADMIN_PASSWORD)

        first = create_camera(
            client,
            name="Front Door",
            host="10.10.0.21",
            with_secondary=True,
        )
        second = create_camera(
            client,
            name="Back Door",
            host="10.10.0.22",
            with_secondary=False,
        )

        first_json = first.json()
        second_json = second.json()
        first_id = uuid.UUID(first_json["id"])
        second_id = uuid.UUID(second_json["id"])

        serialized = json.dumps(first_json)
        assert "super-secret" not in serialized
        assert "top-secret-token" not in serialized
        assert "rtsp://" not in serialized

        profiles = {
            item["adapter_profile_key"]: item["id"]
            for item in first_json["streams"]
        }
        bindings = {
            item["purpose"]: item["stream_profile_id"]
            for item in first_json["bindings"]
        }
        assert bindings["RECORD"] == profiles["manual-primary"]
        assert bindings["LIVE_HIGH"] == profiles["manual-primary"]
        assert bindings["SNAPSHOT"] == profiles["manual-primary"]
        assert bindings["LIVE_LOW"] == profiles["manual-secondary"]
        assert bindings["AI_DETECT"] == profiles["manual-secondary"]

        with app.state.database.session() as session:
            first_camera = session.get(Camera, first_id)
            assert first_camera is not None

            endpoint = session.scalar(
                select(DeviceEndpoint).where(
                    DeviceEndpoint.device_id == first_camera.device_id
                )
            )
            assert endpoint is not None
            assert endpoint.host == "10.10.0.21"
            assert endpoint.port == 8554
            assert endpoint.path is None

            secret_rows = list(
                session.scalars(
                    select(SecretRecord).where(
                        SecretRecord.owner_type == "camera_stream_profile"
                    )
                )
            )
            assert len(secret_rows) == 3
            assert all(
                b"super-secret" not in row.encrypted_payload
                and b"top-secret-token" not in row.encrypted_payload
                for row in secret_rows
            )

            first_primary = session.scalar(
                select(CameraStreamProfile).where(
                    CameraStreamProfile.camera_id == first_camera.id,
                    CameraStreamProfile.adapter_profile_key
                    == "manual-primary",
                )
            )
            assert first_primary is not None
            resolved = CameraService(
                app.state.settings
            ).resolve_stream_uri(session, first_primary)
            assert resolved == (
                "rtsp://alice:super-secret@10.10.0.21:8554/live/main"
                "?token=top-secret-token"
            )

        roles = client.get("/api/v1/roles")
        assert roles.status_code == 200
        viewer_role = next(
            item for item in roles.json() if item["name"] == "Viewer"
        )

        viewer = client.post(
            "/api/v1/users",
            json={
                "username": "viewer",
                "display_name": "Viewer",
                "password": VIEWER_PASSWORD,
                "role_ids": [viewer_role["id"]],
            },
        )
        assert viewer.status_code == 201
        viewer_id = viewer.json()["id"]

        selected = client.put(
            f"/api/v1/users/{viewer_id}/camera-scope",
            json={
                "mode": "selected",
                "camera_ids": [str(first_id)],
            },
        )
        assert selected.status_code == 200

        viewer_token = login(client, "viewer", VIEWER_PASSWORD)

        visible = client.get("/api/v1/cameras")
        assert visible.status_code == 200
        assert [item["name"] for item in visible.json()] == ["Front Door"]

        assert client.get(f"/api/v1/cameras/{first_id}").status_code == 200
        hidden = client.get(f"/api/v1/cameras/{second_id}")
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "camera_not_found"

        denied = client.patch(
            f"/api/v1/cameras/{first_id}",
            json={"name": "Viewer Cannot Rename"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "permission_denied"

        use_token(client, admin_token)

        second_streams = client.get(
            f"/api/v1/cameras/{second_id}/streams"
        )
        assert second_streams.status_code == 200
        foreign_profile_id = second_streams.json()[0]["id"]

        invalid_binding = client.put(
            f"/api/v1/cameras/{first_id}/stream-bindings",
            json={
                "bindings": [
                    {
                        "purpose": "RECORD",
                        "stream_profile_id": foreign_profile_id,
                        "selection_mode": "manual",
                    }
                ]
            },
        )
        assert invalid_binding.status_code == 400
        assert invalid_binding.json()["error"]["code"] == "invalid_stream_profile"

        valid_binding = client.put(
            f"/api/v1/cameras/{first_id}/stream-bindings",
            json={
                "bindings": [
                    {
                        "purpose": "RECORD",
                        "stream_profile_id": profiles["manual-primary"],
                        "selection_mode": "manual",
                    },
                    {
                        "purpose": "LIVE_LOW",
                        "stream_profile_id": profiles["manual-secondary"],
                        "selection_mode": "manual",
                    },
                ]
            },
        )
        assert valid_binding.status_code == 200
        assert {item["purpose"] for item in valid_binding.json()} == {
            "RECORD",
            "LIVE_LOW",
        }

    with app.state.database.session() as session:
        actions = set(session.scalars(select(AuditEvent.action)).all())

    assert "camera.create" in actions
    assert "camera.stream_bindings.update" in actions



def test_camera_enable_disable_queues_runtime_reconcile(
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
        login(client, "admin", ADMIN_PASSWORD)

        created = create_camera(
            client,
            name="Runtime Camera",
            host="10.10.0.30",
            with_secondary=False,
        )
        camera_id = uuid.UUID(created.json()["id"])

        disabled = client.post(
            f"/api/v1/cameras/{camera_id}/disable"
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        enabled = client.post(
            f"/api/v1/cameras/{camera_id}/enable"
        )
        assert enabled.status_code == 200
        assert enabled.json()["enabled"] is True

        assert (
            app.state.recording_tasks.runtime_reconciles
            == [camera_id, camera_id]
        )



def test_camera_retire_restore_preserves_history_identity(
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
        login(client, "admin", ADMIN_PASSWORD)

        created = create_camera(
            client,
            name="Retire Camera",
            host="10.10.0.40",
            with_secondary=False,
        )
        camera_id = uuid.UUID(created.json()["id"])

        retired = client.post(
            f"/api/v1/cameras/{camera_id}/retire"
        )
        assert retired.status_code == 200
        retired_body = retired.json()
        assert retired_body["enabled"] is False
        assert retired_body["retired_at"] is not None

        default_list = client.get("/api/v1/cameras")
        assert default_list.status_code == 200
        assert str(camera_id) not in {
            item["id"] for item in default_list.json()
        }

        history_list = client.get(
            "/api/v1/cameras?include_retired=true"
        )
        assert history_list.status_code == 200
        history_camera = next(
            item
            for item in history_list.json()
            if item["id"] == str(camera_id)
        )
        assert history_camera["retired_at"] is not None
        assert history_camera["enabled"] is False

        still_addressable = client.get(
            f"/api/v1/cameras/{camera_id}"
        )
        assert still_addressable.status_code == 200
        assert still_addressable.json()["name"] == "Retire Camera"

        enable_retired = client.post(
            f"/api/v1/cameras/{camera_id}/enable"
        )
        assert enable_retired.status_code == 409
        assert (
            enable_retired.json()["error"]["code"]
            == "camera_retired"
        )

        restored = client.post(
            f"/api/v1/cameras/{camera_id}/restore"
        )
        assert restored.status_code == 200
        restored_body = restored.json()
        assert restored_body["retired_at"] is None
        assert restored_body["enabled"] is False

        visible_again = client.get("/api/v1/cameras")
        assert visible_again.status_code == 200
        assert str(camera_id) in {
            item["id"] for item in visible_again.json()
        }

        enabled = client.post(
            f"/api/v1/cameras/{camera_id}/enable"
        )
        assert enabled.status_code == 200
        assert enabled.json()["enabled"] is True

        assert app.state.recording_tasks.runtime_reconciles == [
            camera_id,
            camera_id,
        ]

    with app.state.database.session() as session:
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.camera_id == camera_id
                )
            ).all()
        )
    assert "camera.retire" in actions
    assert "camera.restore" in actions
