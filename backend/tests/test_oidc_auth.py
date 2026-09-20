from __future__ import annotations

from pathlib import Path

from fastapi.responses import (
    RedirectResponse,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.auth.models import (
    ExternalIdentity,
    User,
)


ADMIN_PASSWORD = (
    "correct-horse-battery-staple"
)


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key=(
            "oidc-auth-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'oidc.db'}"
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


class FakeOidcRemote:
    def __init__(
        self,
        claims: dict[str, object],
    ) -> None:
        self.claims = claims
        self.redirect_uris: list[str] = []

    async def authorize_redirect(
        self,
        request,
        redirect_uri: str,
    ):
        self.redirect_uris.append(
            redirect_uri
        )
        return RedirectResponse(
            (
                "https://id.example.com/"
                "authorize"
            ),
            status_code=302,
        )

    async def authorize_access_token(
        self,
        request,
    ) -> dict[str, object]:
        return {
            "access_token": (
                "test-access-token"
            ),
            "userinfo": dict(
                self.claims
            ),
        }


def test_oidc_auto_provision_login_and_identity_reuse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    claims: dict[str, object] = {
        "iss": "https://id.example.com",
        "sub": "subject-123",
        "email": "sso@example.com",
        "email_verified": True,
        "preferred_username": "sso-user",
        "name": "SSO User",
    }
    remote = FakeOidcRemote(
        claims
    )

    monkeypatch.setattr(
        (
            "app.modules.auth.oidc_api."
            "_remote_client"
        ),
        lambda request, session, provider: (
            remote
        ),
    )

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": (
                    "Administrator"
                ),
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

        roles = client.get(
            "/api/v1/roles"
        )
        assert roles.status_code == 200
        viewer_role_id = next(
            item["id"]
            for item in roles.json()
            if item["name"] == "Viewer"
        )

        created = client.post(
            "/api/v1/oidc/providers",
            json={
                "key": "authentik",
                "name": "Authentik",
                "issuer": (
                    "https://id.example.com"
                ),
                "client_id": "zero-nvr",
                "client_secret": (
                    "client-secret-value"
                ),
                "auto_provision": True,
                "email_linking": False,
                "default_role_ids": [
                    viewer_role_id
                ],
            },
        )
        assert created.status_code == 201

        client.cookies.clear()
        public = client.get(
            (
                "/api/v1/auth/"
                "oidc/providers"
            )
        )
        assert public.status_code == 200
        assert public.json() == [
            {
                "key": "authentik",
                "name": "Authentik",
            }
        ]

        login = client.get(
            (
                "/api/v1/auth/oidc/"
                "authentik/login"
            ),
            params={
                "next": "/events"
            },
            follow_redirects=False,
        )
        assert login.status_code == 302
        assert login.headers[
            "location"
        ] == (
            "https://id.example.com/"
            "authorize"
        )
        assert (
            remote.redirect_uris[-1]
            .endswith(
                (
                    "/api/v1/auth/oidc/"
                    "authentik/callback"
                )
            )
        )

        callback = client.get(
            (
                "/api/v1/auth/oidc/"
                "authentik/callback"
            ),
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert callback.headers[
            "location"
        ] == "/events"
        assert (
            "zero_nvr_session"
            in client.cookies
        )

        me = client.get(
            "/api/v1/auth/me"
        )
        assert me.status_code == 200
        assert (
            me.json()["username"]
            == "sso-user"
        )
        assert me.json()["roles"] == [
            "Viewer"
        ]

        client.cookies.clear()
        assert client.get(
            (
                "/api/v1/auth/oidc/"
                "authentik/login"
            ),
            follow_redirects=False,
        ).status_code == 302
        second = client.get(
            (
                "/api/v1/auth/oidc/"
                "authentik/callback"
            ),
            follow_redirects=False,
        )
        assert second.status_code == 303

    with app.state.database.session() as session:
        assert session.scalar(
            select(func.count())
            .select_from(
                ExternalIdentity
            )
        ) == 1
        assert session.scalar(
            select(func.count())
            .select_from(User)
        ) == 2


def test_oidc_callback_rejects_unlinked_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    remote = FakeOidcRemote(
        {
            "iss": (
                "https://id.example.com"
            ),
            "sub": "unlinked",
            "email": (
                "unlinked@example.com"
            ),
            "email_verified": True,
        }
    )

    monkeypatch.setattr(
        (
            "app.modules.auth.oidc_api."
            "_remote_client"
        ),
        lambda request, session, provider: (
            remote
        ),
    )

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": (
                    "Administrator"
                ),
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

        created = client.post(
            "/api/v1/oidc/providers",
            json={
                "key": "strict",
                "name": "Strict",
                "issuer": (
                    "https://id.example.com"
                ),
                "client_id": "zero-nvr",
                "client_secret": (
                    "client-secret-value"
                ),
                "auto_provision": False,
                "email_linking": False,
                "default_role_ids": [],
            },
        )
        assert created.status_code == 201

        client.cookies.clear()
        assert client.get(
            (
                "/api/v1/auth/oidc/"
                "strict/login"
            ),
            follow_redirects=False,
        ).status_code == 302

        callback = client.get(
            (
                "/api/v1/auth/oidc/"
                "strict/callback"
            ),
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert (
            callback.headers["location"]
            == (
                "/login?oidc_error="
                "oidc_identity_unlinked"
            )
        )
        assert (
            "zero_nvr_session"
            not in client.cookies
        )
