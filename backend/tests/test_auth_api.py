from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.auth.models import Role, User


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="auth-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'auth-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
        session_ttl_hours=24,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def test_initial_setup_login_me_and_logout(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        status = client.get("/api/v1/setup/status")
        assert status.status_code == 200
        assert status.json() == {"requires_initial_admin": True}

        created = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "email": "admin@example.com",
                "password": "correct-horse-battery-staple",
            },
        )
        assert created.status_code == 201
        assert created.json()["username"] == "admin"
        assert created.json()["roles"] == ["Administrator"]
        assert "system.manage" in created.json()["permissions"]
        assert "user.manage" in created.json()["permissions"]

        status = client.get("/api/v1/setup/status")
        assert status.status_code == 200
        assert status.json() == {"requires_initial_admin": False}

        duplicate = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "second-admin",
                "display_name": "Second Administrator",
                "password": "another-long-secure-password",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "setup_already_completed"

        wrong = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "wrong-password",
            },
        )
        assert wrong.status_code == 401
        assert wrong.json()["error"]["code"] == "invalid_credentials"

        login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "correct-horse-battery-staple",
            },
        )
        assert login.status_code == 200
        assert login.json()["roles"] == ["Administrator"]
        assert "zero_nvr_session" in client.cookies

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "admin"
        assert me.json()["roles"] == ["Administrator"]

        logout = client.post("/api/v1/auth/logout")
        assert logout.status_code == 204

        after_logout = client.get("/api/v1/auth/me")
        assert after_logout.status_code == 401
        assert after_logout.json()["error"]["code"] == "authentication_required"

    with app.state.database.session() as session:
        roles = set(session.scalars(select(Role.name)).all())
        users = session.scalars(select(User)).all()

    assert roles == {"Administrator", "Operator", "Viewer"}
    assert len(users) == 1
    assert users[0].password_hash
    assert users[0].password_hash != "correct-horse-battery-staple"
    assert users[0].password_hash.startswith("$argon2")


def test_setup_rejects_short_password(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": "short",
            },
        )

    assert response.status_code == 422
