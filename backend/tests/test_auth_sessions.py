from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app


COOKIE = "zero_nvr_session"
OLD_PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "new-correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="auth-session-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'auth-sessions.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
        session_ttl_hours=24,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def setup_admin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": OLD_PASSWORD,
        },
    )
    assert response.status_code == 201


def login(client: TestClient, password: str = OLD_PASSWORD) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": password},
    )
    assert response.status_code == 200
    token = client.cookies.get(COOKIE)
    assert token
    return token


def use_token(client: TestClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(COOKIE, token)


def test_password_change_revokes_old_sessions_and_rotates_current_cookie(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        first_token = login(client)
        second_token = login(client)
        assert first_token != second_token

        wrong = client.post(
            "/api/v1/auth/password/change",
            json={
                "current_password": "incorrect-current-password",
                "new_password": NEW_PASSWORD,
            },
        )
        assert wrong.status_code == 400
        assert wrong.json()["error"]["code"] == "invalid_current_password"

        changed = client.post(
            "/api/v1/auth/password/change",
            json={
                "current_password": OLD_PASSWORD,
                "new_password": NEW_PASSWORD,
            },
        )
        assert changed.status_code == 200
        replacement_token = client.cookies.get(COOKIE)
        assert replacement_token
        assert replacement_token not in {first_token, second_token}

        sessions = client.get("/api/v1/sessions")
        assert sessions.status_code == 200
        assert len(sessions.json()) == 1
        assert sessions.json()[0]["current"] is True

        use_token(client, first_token)
        assert client.get("/api/v1/auth/me").status_code == 401

        use_token(client, second_token)
        assert client.get("/api/v1/auth/me").status_code == 401

        use_token(client, replacement_token)
        assert client.get("/api/v1/auth/me").status_code == 200

        client.cookies.clear()
        old_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": OLD_PASSWORD},
        )
        assert old_login.status_code == 401

        new_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": NEW_PASSWORD},
        )
        assert new_login.status_code == 200


def test_user_can_revoke_other_and_current_sessions(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        first_token = login(client)
        second_token = login(client)

        use_token(client, first_token)
        sessions = client.get("/api/v1/sessions")
        assert sessions.status_code == 200
        items = sessions.json()
        assert len(items) == 2

        current = next(item for item in items if item["current"])
        other = next(item for item in items if not item["current"])

        revoked_other = client.delete(f"/api/v1/sessions/{other['id']}")
        assert revoked_other.status_code == 204

        use_token(client, second_token)
        assert client.get("/api/v1/auth/me").status_code == 401

        use_token(client, first_token)
        remaining = client.get("/api/v1/sessions")
        assert remaining.status_code == 200
        assert len(remaining.json()) == 1
        assert remaining.json()[0]["id"] == current["id"]

        revoked_current = client.delete(f"/api/v1/sessions/{current['id']}")
        assert revoked_current.status_code == 204
        assert client.cookies.get(COOKIE) is None

        assert client.get("/api/v1/auth/me").status_code == 401
