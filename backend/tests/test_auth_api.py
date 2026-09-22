from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.auth.models import Role, User
from app.modules.system.models import SystemSetting


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


def test_initial_setup_claim_does_not_reopen_if_users_are_removed(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": "correct-horse-battery-staple",
            },
        )
        assert created.status_code == 201

        with app.state.database.session() as session:
            claim = session.get(
                SystemSetting,
                "bootstrap.initial_admin",
            )
            assert claim is not None
            for user in session.scalars(
                select(User)
            ).all():
                session.delete(user)
            session.commit()

        status = client.get("/api/v1/setup/status")
        assert status.status_code == 200
        assert status.json() == {
            "requires_initial_admin": False
        }

        duplicate = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "replacement-admin",
                "display_name": "Replacement Administrator",
                "password": "another-long-secure-password",
            },
        )
        assert duplicate.status_code == 409
        assert (
            duplicate.json()["error"]["code"]
            == "setup_already_completed"
        )


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



class FakeNotificationTasks:
    def __init__(self) -> None:
        self.delivery_ids = []

    def deliver(self, delivery_id) -> None:
        self.delivery_ids.append(delivery_id)


class CaptureMailAdapter:
    calls = []

    def __init__(self, *, url: str) -> None:
        self.url = url

    def notify(
        self,
        *,
        title: str,
        body: str,
        notify_type: str,
    ) -> None:
        self.calls.append(
            {
                "url": self.url,
                "title": title,
                "body": body,
                "notify_type": notify_type,
            }
        )


def test_self_service_password_reset_is_single_use_non_enumerating_and_revokes_sessions(
    tmp_path: Path,
) -> None:
    from urllib.parse import parse_qs, urlsplit

    from app.modules.audit.models import AuditEvent
    from app.modules.auth.models import PasswordResetToken
    from app.modules.auth.password_reset import PasswordResetService
    from app.modules.notifications.delivery import NotificationDeliveryService
    from app.modules.notifications.models import NotificationDelivery

    app = make_app(tmp_path)
    fake_tasks = FakeNotificationTasks()
    app.state.notification_tasks = fake_tasks

    old_password = "correct-horse-battery-staple"
    new_password = "correct-horse-battery-new-password"

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "email": "admin@example.com",
                "password": old_password,
            },
        ).status_code == 201
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": old_password,
            },
        ).status_code == 200

        target = client.post(
            "/api/v1/notification-targets",
            json={
                "name": "Security email",
                "config": {
                    "password_reset": True,
                },
                "url": (
                    "mailtos://smtp-user:smtp-pass@mail.example.com"
                    "?from=zero-nvr@example.com"
                    "&to=old@example.com"
                    "&cc=copy@example.com"
                    "&bcc=hidden@example.com"
                ),
            },
        )
        assert target.status_code == 201

        requested = client.post(
            "/api/v1/auth/password-reset/request",
            json={"identifier": "admin@example.com"},
        )
        assert requested.status_code == 202
        assert requested.json() == {"accepted": True}
        assert len(fake_tasks.delivery_ids) == 1

        throttled = client.post(
            "/api/v1/auth/password-reset/request",
            json={"identifier": "admin"},
        )
        assert throttled.status_code == 202
        assert throttled.json() == {"accepted": True}
        assert len(fake_tasks.delivery_ids) == 1

        unknown = client.post(
            "/api/v1/auth/password-reset/request",
            json={"identifier": "nobody@example.com"},
        )
        assert unknown.status_code == 202
        assert unknown.json() == {"accepted": True}
        assert len(fake_tasks.delivery_ids) == 1

        delivery_id = fake_tasks.delivery_ids[0]
        with app.state.database.session() as session:
            reset = session.scalar(
                select(PasswordResetToken)
            )
            assert reset is not None
            token = PasswordResetService(
                app.state.settings
            ).token_for_record(reset)
            assert reset.token_hash != token
            delivery = session.get(
                NotificationDelivery,
                delivery_id,
            )
            assert delivery is not None
            assert delivery.purpose == "password_reset"
            assert token not in delivery.body

        CaptureMailAdapter.calls = []
        delivered = NotificationDeliveryService(
            app.state.settings,
            adapter_factory=CaptureMailAdapter,
        ).execute(
            app.state.database,
            delivery_id=delivery_id,
        )
        assert delivered.state == "SENT"
        assert delivered.delivered is True
        assert len(CaptureMailAdapter.calls) == 1

        sent = CaptureMailAdapter.calls[0]
        parsed = urlsplit(sent["url"])
        query = parse_qs(parsed.query)
        assert parsed.scheme == "mailtos"
        assert query["to"] == ["admin@example.com"]
        assert "cc" not in query
        assert "bcc" not in query
        assert "old@example.com" not in sent["url"]
        assert token in sent["body"]

        completed = client.post(
            "/api/v1/auth/password-reset/complete",
            json={
                "token": token,
                "new_password": new_password,
            },
        )
        assert completed.status_code == 200
        assert completed.json() == {"ok": True}

        assert client.get(
            "/api/v1/auth/me"
        ).status_code == 401

        reused = client.post(
            "/api/v1/auth/password-reset/complete",
            json={
                "token": token,
                "new_password": (
                    "another-correct-horse-battery-password"
                ),
            },
        )
        assert reused.status_code == 400
        assert (
            reused.json()["error"]["code"]
            == "password_reset_token_invalid"
        )

        old_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": old_password,
            },
        )
        assert old_login.status_code == 401

        new_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": new_password,
            },
        )
        assert new_login.status_code == 200

    with app.state.database.session() as session:
        actions = set(
            session.scalars(
                select(AuditEvent.action)
            ).all()
        )
    assert "auth.password_reset.request" in actions
    assert "auth.password_reset.complete" in actions



def test_personal_api_token_is_hashed_scoped_and_revocable(
    tmp_path: Path,
) -> None:
    import uuid

    from app.modules.auth.models import PersonalApiToken

    app = make_app(tmp_path)

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "email": "admin@example.com",
                "password": "correct-horse-battery-staple",
            },
        ).status_code == 201
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "correct-horse-battery-staple",
            },
        ).status_code == 200

        created = client.post(
            "/api/v1/api-tokens",
            json={
                "name": "Home Assistant",
                "permissions": [
                    "camera.view",
                    "system.view",
                ],
            },
        )
        assert created.status_code == 201
        body = created.json()
        token = body["token"]
        token_id = body["id"]
        assert token.startswith("znr_pat_")
        assert body["permissions"] == [
            "camera.view",
            "system.view",
        ]

        listed = client.get("/api/v1/api-tokens")
        assert listed.status_code == 200
        listed_body = listed.json()
        assert len(listed_body) == 1
        assert "token" not in listed_body[0]

        with app.state.database.session() as session:
            stored = session.get(
                PersonalApiToken,
                uuid.UUID(token_id),
            )
            assert stored is not None
            assert stored.token_hash != token

        client.cookies.clear()
        headers = {
            "Authorization": f"Bearer {token}"
        }

        me = client.get(
            "/api/v1/auth/me",
            headers=headers,
        )
        assert me.status_code == 200
        assert me.json()["username"] == "admin"
        assert me.json()["permissions"] == [
            "camera.view",
            "system.view",
        ]

        cameras = client.get(
            "/api/v1/cameras",
            headers=headers,
        )
        assert cameras.status_code == 200

        denied = client.get(
            "/api/v1/users",
            headers=headers,
        )
        assert denied.status_code == 403
        assert (
            denied.json()["error"]["code"]
            == "permission_denied"
        )

        interactive_only = client.get(
            "/api/v1/sessions",
            headers=headers,
        )
        assert interactive_only.status_code == 403
        assert (
            interactive_only.json()["error"]["code"]
            == "interactive_session_required"
        )

        with app.state.database.session() as session:
            used = session.get(
                PersonalApiToken,
                uuid.UUID(token_id),
            )
            assert used is not None
            assert used.last_used_at is not None

        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "correct-horse-battery-staple",
            },
        ).status_code == 200

        revoked = client.delete(
            f"/api/v1/api-tokens/{token_id}"
        )
        assert revoked.status_code == 204

        client.cookies.clear()
        after_revoke = client.get(
            "/api/v1/auth/me",
            headers=headers,
        )
        assert after_revoke.status_code == 401



def test_login_and_reset_rate_limits_are_non_enumerating(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "email": "admin@example.com",
                "password": "correct-horse-battery-staple",
            },
        ).status_code == 201

        for _ in range(4):
            wrong = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "admin",
                    "password": "wrong-password",
                },
            )
            assert wrong.status_code == 401
            assert (
                wrong.json()["error"]["code"]
                == "invalid_credentials"
            )

        blocked = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "wrong-password",
            },
        )
        assert blocked.status_code == 429
        assert (
            blocked.json()["error"]["code"]
            == "too_many_attempts"
        )
        assert (
            blocked.json()["error"]["details"][
                "retry_after_seconds"
            ]
            >= 1
        )

        still_blocked = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "correct-horse-battery-staple",
            },
        )
        assert still_blocked.status_code == 429

        for index in range(12):
            reset = client.post(
                "/api/v1/auth/password-reset/request",
                json={
                    "identifier": (
                        "admin@example.com"
                        if index % 2 == 0
                        else f"missing-{index}@example.com"
                    )
                },
            )
            assert reset.status_code == 202
            assert reset.json() == {
                "accepted": True
            }

    with app.state.database.session() as session:
        from app.modules.audit.models import AuditEvent

        actions = set(
            session.scalars(
                select(AuditEvent.action)
            ).all()
        )
    assert "auth.login.rate_limited" in actions
    assert "auth.password_reset.rate_limited" in actions
