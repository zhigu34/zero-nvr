from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.cameras.models import Camera


PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key=(
            "live-layout-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'live-layout.db'}"
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


def test_live_view_layout_crud_default_and_scope(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        assert client.get(
            "/api/v1/live-layouts"
        ).status_code == 401

        setup = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": PASSWORD,
            },
        )
        assert setup.status_code == 201
        user_id = setup.json()["id"]

        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": PASSWORD,
            },
        ).status_code == 200

        with app.state.database.session() as session:
            camera_a = Camera(
                channel_key="layout-a",
                name="Front Door",
                enabled=True,
            )
            camera_b = Camera(
                channel_key="layout-b",
                name="Garage",
                enabled=True,
            )
            session.add_all(
                [camera_a, camera_b]
            )
            session.commit()
            camera_a_id = str(camera_a.id)
            camera_b_id = str(camera_b.id)

        first = client.post(
            "/api/v1/live-layouts",
            json={
                "name": "Perimeter",
                "is_default": False,
                "layout": {
                    "slots": 4,
                    "camera_ids": [
                        camera_a_id,
                        camera_b_id,
                    ],
                    "camera_panel_open": True,
                },
            },
        )
        assert first.status_code == 201
        first_body = first.json()
        assert first_body["is_default"] is True

        second = client.post(
            "/api/v1/live-layouts",
            json={
                "name": "Garage only",
                "is_default": True,
                "layout": {
                    "slots": 1,
                    "camera_ids": [
                        camera_b_id
                    ],
                    "camera_panel_open": False,
                },
            },
        )
        assert second.status_code == 201
        second_body = second.json()
        assert second_body["is_default"] is True

        listed = client.get(
            "/api/v1/live-layouts"
        )
        assert listed.status_code == 200
        assert [
            item["name"]
            for item in listed.json()
        ] == [
            "Garage only",
            "Perimeter",
        ]
        assert sum(
            item["is_default"]
            for item in listed.json()
        ) == 1

        promoted = client.patch(
            (
                "/api/v1/live-layouts/"
                f"{first_body['id']}"
            ),
            json={
                "is_default": True,
                "layout": {
                    "slots": 9,
                    "camera_ids": [
                        camera_a_id,
                        camera_b_id,
                    ],
                    "camera_panel_open": False,
                },
            },
        )
        assert promoted.status_code == 200
        assert promoted.json()["is_default"] is True
        assert (
            promoted.json()["layout"]["slots"]
            == 9
        )

        scoped = client.put(
            (
                "/api/v1/users/"
                f"{user_id}/camera-scope"
            ),
            json={
                "mode": "selected",
                "camera_ids": [camera_a_id],
            },
        )
        assert scoped.status_code == 200

        visible = client.get(
            "/api/v1/live-layouts"
        )
        assert visible.status_code == 200
        by_name = {
            item["name"]: item
            for item in visible.json()
        }
        assert (
            by_name["Perimeter"]["layout"][
                "camera_ids"
            ]
            == [camera_a_id]
        )
        assert (
            by_name["Garage only"]["layout"][
                "camera_ids"
            ]
            == []
        )

        unavailable = client.post(
            "/api/v1/live-layouts",
            json={
                "name": "Hidden camera",
                "layout": {
                    "slots": 1,
                    "camera_ids": [
                        camera_b_id
                    ],
                    "camera_panel_open": True,
                },
            },
        )
        assert unavailable.status_code == 400
        assert (
            unavailable.json()["error"]["code"]
            == (
                "live_view_layout_"
                "camera_unavailable"
            )
        )

        duplicate_name = client.post(
            "/api/v1/live-layouts",
            json={
                "name": "Perimeter",
                "layout": {
                    "slots": 1,
                    "camera_ids": [
                        camera_a_id
                    ],
                    "camera_panel_open": True,
                },
            },
        )
        assert duplicate_name.status_code == 409
        assert (
            duplicate_name.json()["error"]["code"]
            == "live_view_layout_name_conflict"
        )

        assert client.delete(
            (
                "/api/v1/live-layouts/"
                f"{first_body['id']}"
            )
        ).status_code == 204

        missing = client.patch(
            (
                "/api/v1/live-layouts/"
                f"{uuid.uuid4()}"
            ),
            json={"is_default": True},
        )
        assert missing.status_code == 404
        assert (
            missing.json()["error"]["code"]
            == "live_view_layout_not_found"
        )
