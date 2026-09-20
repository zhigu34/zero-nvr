from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app


ADMIN_PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="camera-groups-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'camera-groups.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def create_camera(client: TestClient, name: str, host: str) -> str:
    response = client.post(
        "/api/v1/cameras",
        json={
            "mode": "manual_rtsp",
            "name": name,
            "location": None,
            "storage_label": None,
            "primary_stream": {
                "name": "Main",
                "rtsp_url": f"rtsp://{host}/main",
            },
            "secondary_stream": None,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_camera_group_crud_hierarchy_and_scope_guard(
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
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200

        front = create_camera(
            client,
            "Front Door",
            "front.local",
        )
        driveway = create_camera(
            client,
            "Driveway",
            "driveway.local",
        )

        exterior = client.post(
            "/api/v1/camera-groups",
            json={
                "name": "Exterior",
                "description": "Outside cameras",
                "parent_id": None,
                "camera_ids": [front],
            },
        )
        assert exterior.status_code == 201
        exterior_id = exterior.json()["id"]
        assert exterior.json()["camera_ids"] == [front]

        entrances = client.post(
            "/api/v1/camera-groups",
            json={
                "name": "Entrances",
                "description": None,
                "parent_id": exterior_id,
                "camera_ids": [driveway],
            },
        )
        assert entrances.status_code == 201
        entrances_id = entrances.json()["id"]

        cycle = client.patch(
            f"/api/v1/camera-groups/{exterior_id}",
            json={"parent_id": entrances_id},
        )
        assert cycle.status_code == 400
        assert (
            cycle.json()["error"]["code"]
            == "camera_group_parent_cycle"
        )

        groups = client.get("/api/v1/camera-groups")
        assert groups.status_code == 200
        assert {item["name"] for item in groups.json()} == {
            "Exterior",
            "Entrances",
        }

        roles = client.get("/api/v1/roles")
        viewer_id = next(
            item["id"]
            for item in roles.json()
            if item["name"] == "Viewer"
        )
        scope = client.put(
            f"/api/v1/roles/{viewer_id}/camera-scope",
            json={
                "mode": "selected",
                "camera_ids": [],
                "camera_group_ids": [entrances_id],
            },
        )
        assert scope.status_code == 200

        blocked = client.delete(
            f"/api/v1/camera-groups/{entrances_id}"
        )
        assert blocked.status_code == 409
        assert (
            blocked.json()["error"]["code"]
            == "camera_group_in_use"
        )

        assert client.put(
            f"/api/v1/roles/{viewer_id}/camera-scope",
            json={
                "mode": "all",
                "camera_ids": [],
                "camera_group_ids": [],
            },
        ).status_code == 200

        assert client.delete(
            f"/api/v1/camera-groups/{entrances_id}"
        ).status_code == 204
        assert client.delete(
            f"/api/v1/camera-groups/{exterior_id}"
        ).status_code == 204
