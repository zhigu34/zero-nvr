from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.auth.camera_scope import CameraScopeService
from app.modules.auth.models import Role, User
from app.modules.cameras.models import Camera, CameraGroup, CameraGroupMember


PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="camera-scope-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'camera-scope.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def test_camera_scope_inheritance_override_and_group_descendants(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": PASSWORD,
            },
        )
        assert created.status_code == 201
        admin_id = uuid.UUID(created.json()["id"])

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": PASSWORD},
        )
        assert login.status_code == 200

        with app.state.database.session() as session:
            camera_a = Camera(
                channel_key="a",
                name="Camera A",
                enabled=True,
            )
            camera_b = Camera(
                channel_key="b",
                name="Camera B",
                enabled=True,
            )
            parent = CameraGroup(name="Building")
            child = CameraGroup(name="Floor 1")
            session.add_all([camera_a, camera_b, parent, child])
            session.flush()
            child.parent_id = parent.id
            session.add_all(
                [
                    CameraGroupMember(
                        camera_group_id=parent.id,
                        camera_id=camera_a.id,
                    ),
                    CameraGroupMember(
                        camera_group_id=child.id,
                        camera_id=camera_b.id,
                    ),
                ]
            )
            session.commit()
            camera_a_id = camera_a.id
            camera_b_id = camera_b.id
            parent_id = parent.id

        roles = client.get("/api/v1/roles")
        assert roles.status_code == 200
        admin_role = next(
            item for item in roles.json() if item["name"] == "Administrator"
        )

        role_scope = client.get(
            f"/api/v1/roles/{admin_role['id']}/camera-scope"
        )
        assert role_scope.status_code == 200
        assert role_scope.json()["mode"] == "all"

        with app.state.database.session() as session:
            admin = session.get(User, admin_id)
            assert admin is not None
            effective = CameraScopeService.effective_scope(
                session,
                user_id=admin.id,
                role_ids=[role.id for role in admin.roles],
            )
            assert effective.all_cameras is True
            assert effective.allows(camera_a_id)
            assert effective.allows(camera_b_id)

        selected = client.put(
            f"/api/v1/users/{admin_id}/camera-scope",
            json={
                "mode": "selected",
                "camera_group_ids": [str(parent_id)],
            },
        )
        assert selected.status_code == 200
        assert selected.json()["mode"] == "selected"

        with app.state.database.session() as session:
            admin = session.get(User, admin_id)
            assert admin is not None
            effective = CameraScopeService.effective_scope(
                session,
                user_id=admin.id,
                role_ids=[role.id for role in admin.roles],
            )
            assert effective.all_cameras is False
            assert effective.camera_ids == frozenset(
                {camera_a_id, camera_b_id}
            )

        none_scope = client.put(
            f"/api/v1/users/{admin_id}/camera-scope",
            json={"mode": "none"},
        )
        assert none_scope.status_code == 200

        with app.state.database.session() as session:
            admin = session.get(User, admin_id)
            assert admin is not None
            effective = CameraScopeService.effective_scope(
                session,
                user_id=admin.id,
                role_ids=[role.id for role in admin.roles],
            )
            assert effective.all_cameras is False
            assert not effective.camera_ids

        inherited = client.put(
            f"/api/v1/users/{admin_id}/camera-scope",
            json={"mode": "inherit"},
        )
        assert inherited.status_code == 200
        assert inherited.json()["mode"] == "inherit"

        with app.state.database.session() as session:
            admin = session.get(User, admin_id)
            assert admin is not None
            effective = CameraScopeService.effective_scope(
                session,
                user_id=admin.id,
                role_ids=[role.id for role in admin.roles],
            )
            assert effective.all_cameras is True


def test_custom_role_defaults_to_no_camera_access(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": PASSWORD,
            },
        )
        client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": PASSWORD},
        )

        role = client.post(
            "/api/v1/roles",
            json={
                "name": "Restricted Viewer",
                "permissions": ["camera.view"],
            },
        )
        assert role.status_code == 201

        scope = client.get(
            f"/api/v1/roles/{role.json()['id']}/camera-scope"
        )
        assert scope.status_code == 200
        assert scope.json() == {
            "mode": "none",
            "camera_ids": [],
            "camera_group_ids": [],
        }

def test_camera_scope_filters_camera_api_and_hides_out_of_scope_camera(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": PASSWORD,
            },
        )
        assert setup.status_code == 201

        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": PASSWORD,
            },
        ).status_code == 200

        roles = client.get("/api/v1/roles")
        assert roles.status_code == 200
        viewer_role_id = next(
            item["id"]
            for item in roles.json()
            if item["name"] == "Viewer"
        )

        viewer = client.post(
            "/api/v1/users",
            json={
                "username": "viewer",
                "display_name": "Viewer",
                "password": PASSWORD,
                "role_ids": [viewer_role_id],
            },
        )
        assert viewer.status_code == 201
        viewer_id = viewer.json()["id"]

        with app.state.database.session() as session:
            camera_a = Camera(
                channel_key="scope-a",
                name="Scope Camera A",
                enabled=True,
            )
            camera_b = Camera(
                channel_key="scope-b",
                name="Scope Camera B",
                enabled=True,
            )
            camera_c = Camera(
                channel_key="scope-c",
                name="Scope Camera C",
                enabled=True,
            )
            parent = CameraGroup(name="Scoped Building")
            child = CameraGroup(name="Scoped Floor")
            session.add_all(
                [
                    camera_a,
                    camera_b,
                    camera_c,
                    parent,
                    child,
                ]
            )
            session.flush()
            child.parent_id = parent.id
            session.add_all(
                [
                    CameraGroupMember(
                        camera_group_id=parent.id,
                        camera_id=camera_a.id,
                    ),
                    CameraGroupMember(
                        camera_group_id=child.id,
                        camera_id=camera_b.id,
                    ),
                ]
            )
            session.commit()
            camera_a_id = camera_a.id
            camera_b_id = camera_b.id
            camera_c_id = camera_c.id
            parent_id = parent.id

        selected = client.put(
            f"/api/v1/users/{viewer_id}/camera-scope",
            json={
                "mode": "selected",
                "camera_group_ids": [str(parent_id)],
            },
        )
        assert selected.status_code == 200

        client.cookies.clear()
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "viewer",
                "password": PASSWORD,
            },
        ).status_code == 200

        cameras = client.get("/api/v1/cameras")
        assert cameras.status_code == 200
        assert {
            item["id"]
            for item in cameras.json()
        } == {
            str(camera_a_id),
            str(camera_b_id),
        }

        allowed = client.get(
            f"/api/v1/cameras/{camera_a_id}"
        )
        assert allowed.status_code == 200

        hidden = client.get(
            f"/api/v1/cameras/{camera_c_id}"
        )
        assert hidden.status_code == 404
        assert (
            hidden.json()["error"]["code"]
            == "camera_not_found"
        )

