from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.core.security import SecretStore
from app.main import create_app


ADMIN_PASSWORD = "correct-horse-battery-staple"
NEW_KEY = "n" * 40
OLD_KEY = "o" * 40


def make_app(
    tmp_path: Path,
    *,
    include_previous: bool,
):
    settings = Settings(
        secret_key=NEW_KEY,
        secret_key_previous=(
            [OLD_KEY]
            if include_previous
            else []
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'secret-store.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=tmp_path / "recordings",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(
        app.state.database.engine
    )
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


def seed_legacy_secret(app) -> uuid.UUID:
    old_store = SecretStore(
        Settings(secret_key=OLD_KEY)
    )
    with app.state.database.session() as session:
        secret_ref = old_store.create_json(
            session,
            kind="rotation_test",
            owner_type="system_test",
            owner_id=uuid.uuid4(),
            value={"password": "legacy-secret"},
        )
        session.commit()
        return secret_ref


def test_secret_store_health_and_rotation_workflow(
    tmp_path: Path,
) -> None:
    app = make_app(
        tmp_path,
        include_previous=True,
    )
    seed_legacy_secret(app)

    with TestClient(app) as client:
        setup_admin(client)

        before = client.get(
            "/api/v1/system/secret-store"
        )
        assert before.status_code == 200
        before_body = before.json()
        assert before_body["status"] == (
            "ROTATION_REQUIRED"
        )
        assert before_body["total_records"] == 1
        assert before_body["current_records"] == 0
        assert before_body["stale_records"] == 1
        assert before_body["unreadable_records"] == 0
        assert before_body["previous_key_count"] == 1
        assert before_body["rotation_ready"] is True

        rotated = client.post(
            "/api/v1/system/secret-store/rotate"
        )
        assert rotated.status_code == 200
        rotated_body = rotated.json()
        assert rotated_body["total_records"] == 1
        assert rotated_body["rotated_records"] == 1
        assert (
            rotated_body["already_current_records"]
            == 0
        )
        assert (
            rotated_body["health"]["status"]
            == "OK"
        )
        assert (
            rotated_body["health"]["current_records"]
            == 1
        )
        assert (
            rotated_body["health"]["stale_records"]
            == 0
        )

        after = client.get(
            "/api/v1/system/secret-store"
        )
        assert after.status_code == 200
        assert after.json()["status"] == "OK"
        assert (
            after.json()["rotation_ready"]
            is False
        )


def test_secret_store_rotation_refuses_missing_old_key(
    tmp_path: Path,
) -> None:
    app = make_app(
        tmp_path,
        include_previous=False,
    )
    secret_ref = seed_legacy_secret(app)

    with TestClient(app) as client:
        setup_admin(client)

        health = client.get(
            "/api/v1/system/secret-store"
        )
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ERROR"
        assert body["stale_records"] == 1
        assert body["unreadable_records"] == 1
        assert body["rotation_ready"] is False

        response = client.post(
            "/api/v1/system/secret-store/rotate"
        )
        assert response.status_code == 409
        assert (
            response.json()["error"]["code"]
            == "secret_store_rotation_unavailable"
        )

    old_store = SecretStore(
        Settings(secret_key=OLD_KEY)
    )
    with app.state.database.session() as session:
        assert old_store.read_json(
            session,
            secret_ref,
            kind="rotation_test",
            owner_type="system_test",
        ) == {
            "password": "legacy-secret",
        }
