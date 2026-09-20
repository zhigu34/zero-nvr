from __future__ import annotations

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
        admin_id = created.json()["id"]

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
