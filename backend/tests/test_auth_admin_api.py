from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.audit.models import AuditEvent


COOKIE = "zero_nvr_session"
ADMIN_PASSWORD = "correct-horse-battery-staple"
VIEWER_PASSWORD = "viewer-correct-horse-battery"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="auth-admin-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'auth-admin.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
        session_ttl_hours=24,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
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


def test_user_role_permissions_last_admin_and_audit(tmp_path: Path) -> None:
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
        admin_id = setup.json()["id"]

        admin_token = login(client, "admin", ADMIN_PASSWORD)

        permissions = client.get("/api/v1/permissions")
        assert permissions.status_code == 200
        assert {
            "camera.view",
            "recording.view",
            "user.manage",
        } <= set(permissions.json())

        roles = client.get("/api/v1/roles")
        assert roles.status_code == 200
        role_by_name = {item["name"]: item for item in roles.json()}
        assert set(role_by_name) == {"Administrator", "Operator", "Viewer"}

        viewer_role_id = role_by_name["Viewer"]["id"]

        created = client.post(
            "/api/v1/users",
            json={
                "username": "viewer",
                "display_name": "Viewer User",
                "email": "viewer@example.com",
                "password": VIEWER_PASSWORD,
                "role_ids": [viewer_role_id],
            },
        )
        assert created.status_code == 201
        viewer_id = created.json()["id"]
        assert created.json()["roles"][0]["name"] == "Viewer"

        viewer_token = login(client, "viewer", VIEWER_PASSWORD)
        denied = client.get("/api/v1/users")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "permission_denied"
        assert denied.json()["error"]["details"]["permission"] == "user.manage"

        use_token(client, admin_token)

        reset_issue = client.post(
            f"/api/v1/users/{viewer_id}/password-reset"
        )
        assert reset_issue.status_code == 200
        reset_token = reset_issue.json()["token"]
        assert reset_token.startswith("znr1.")
        assert reset_issue.json()["expires_at"]

        use_token(client, viewer_token)
        assert client.get("/api/v1/auth/me").status_code == 200

        completed = client.post(
            "/api/v1/auth/password-reset/complete",
            json={
                "token": reset_token,
                "new_password": "viewer-new-correct-horse-battery",
            },
        )
        assert completed.status_code == 200

        assert client.get("/api/v1/auth/me").status_code == 401

        old_password = client.post(
            "/api/v1/auth/login",
            json={
                "username": "viewer",
                "password": VIEWER_PASSWORD,
            },
        )
        assert old_password.status_code == 401

        client.cookies.clear()
        new_viewer_token = login(
            client,
            "viewer",
            "viewer-new-correct-horse-battery",
        )
        assert new_viewer_token

        use_token(client, admin_token)

        last_admin_disable = client.post(
            f"/api/v1/users/{admin_id}/disable"
        )
        assert last_admin_disable.status_code == 409
        assert last_admin_disable.json()["error"]["code"] == "last_administrator"

        remove_admin_role = client.patch(
            f"/api/v1/users/{admin_id}",
            json={"role_ids": [viewer_role_id]},
        )
        assert remove_admin_role.status_code == 409
        assert remove_admin_role.json()["error"]["code"] == "last_administrator"

        custom = client.post(
            "/api/v1/roles",
            json={
                "name": "Auditor",
                "description": "Read-only event and audit access",
                "permissions": ["event.view", "audit.view"],
            },
        )
        assert custom.status_code == 201
        assert custom.json()["built_in"] is False
        assert custom.json()["permissions"] == ["audit.view", "event.view"]

        invalid_role = client.post(
            "/api/v1/roles",
            json={
                "name": "Invalid Role",
                "permissions": ["everything.do"],
            },
        )
        assert invalid_role.status_code == 400
        assert invalid_role.json()["error"]["code"] == "invalid_permissions"

        mutate_builtin = client.patch(
            f"/api/v1/roles/{viewer_role_id}",
            json={"permissions": ["camera.view"]},
        )
        assert mutate_builtin.status_code == 409
        assert mutate_builtin.json()["error"]["code"] == "builtin_role_immutable"

        disabled = client.post(
            f"/api/v1/users/{viewer_id}/disable"
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        use_token(client, new_viewer_token)
        assert client.get("/api/v1/auth/me").status_code == 401

        use_token(client, admin_token)
        listed = client.get("/api/v1/users")
        assert listed.status_code == 200
        assert {item["username"] for item in listed.json()} == {"admin", "viewer"}

    with app.state.database.session() as session:
        actions = set(session.scalars(select(AuditEvent.action)).all())

    assert {
        "user.create",
        "user.disable",
        "user.password_reset.issue",
        "auth.password_reset.complete",
        "role.create",
    } <= actions



def test_oidc_provider_configuration_encrypts_secret_and_validates_roles(
    tmp_path: Path,
) -> None:
    from app.modules.auth.models import SecretRecord
    from app.modules.auth.oidc import (
        OidcProviderSettingsService,
    )

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

        roles = client.get("/api/v1/roles")
        assert roles.status_code == 200
        viewer_role_id = next(
            item["id"]
            for item in roles.json()
            if item["name"] == "Viewer"
        )

        invalid_http = client.post(
            "/api/v1/oidc/providers",
            json={
                "key": "unsafe",
                "name": "Unsafe",
                "issuer": "http://idp.example.com",
                "client_id": "zero-nvr",
                "client_secret": "top-secret-client-value",
                "auto_provision": True,
                "default_role_ids": [viewer_role_id],
            },
        )
        assert invalid_http.status_code == 400
        assert (
            invalid_http.json()["error"]["code"]
            == "oidc_issuer_insecure"
        )

        created = client.post(
            "/api/v1/oidc/providers",
            json={
                "key": "authentik",
                "name": "Authentik",
                "issuer": (
                    "https://id.example.com/application/o/zero-nvr/"
                ),
                "client_id": "zero-nvr",
                "client_secret": "top-secret-client-value",
                "auto_provision": True,
                "email_linking": False,
                "default_role_ids": [viewer_role_id],
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["key"] == "authentik"
        assert body["issuer"] == (
            "https://id.example.com/application/o/zero-nvr"
        )
        assert body["client_secret_configured"] is True
        assert "top-secret-client-value" not in created.text

        with app.state.database.session() as session:
            initial_provider = (
                OidcProviderSettingsService.get(
                    session,
                    "authentik",
                )
            )
            initial_secret_ref = (
                initial_provider.secret_ref
            )
            assert initial_secret_ref is not None

        listed = client.get("/api/v1/oidc/providers")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        conflict = client.post(
            "/api/v1/oidc/providers",
            json={
                "key": "authentik",
                "name": "Duplicate",
                "issuer": "https://id2.example.com",
                "client_id": "duplicate",
                "client_secret": "duplicate-secret",
                "default_role_ids": [],
            },
        )
        assert conflict.status_code == 409

        updated = client.patch(
            "/api/v1/oidc/providers/authentik",
            json={
                "name": "Authentik SSO",
                "client_secret_action": "replace",
                "client_secret": "replacement-secret-value",
                "email_linking": True,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Authentik SSO"
        assert updated.json()["email_linking"] is True
        assert "replacement-secret-value" not in updated.text

        with app.state.database.session() as session:
            provider = OidcProviderSettingsService.get(
                session,
                "authentik",
            )
            secret = OidcProviderSettingsService(
                app.state.settings
            ).client_secret(
                session,
                provider,
            )
            assert secret == "replacement-secret-value"
            assert provider.secret_ref is not None
            assert provider.secret_ref != initial_secret_ref
            assert (
                session.get(
                    SecretRecord,
                    initial_secret_ref,
                )
                is None
            )

            stored = session.get(
                SecretRecord,
                provider.secret_ref,
            )
            assert stored is not None
            assert (
                b"replacement-secret-value"
                not in stored.encrypted_payload
            )

        deleted = client.delete(
            "/api/v1/oidc/providers/authentik"
        )
        assert deleted.status_code == 204
        assert client.get(
            "/api/v1/oidc/providers"
        ).json() == []
