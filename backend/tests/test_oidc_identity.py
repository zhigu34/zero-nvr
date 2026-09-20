from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base
from app.core.errors import ApiError
from app.main import create_app
from app.modules.auth.models import (
    ExternalIdentity,
    Role,
    User,
)
from app.modules.auth.oidc import (
    OidcProviderConfig,
)
from app.modules.auth.oidc_identity import (
    OidcIdentityService,
)


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key=(
            "oidc-identity-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'oidc-identity.db'}"
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


def provider(
    *,
    auto_provision: bool,
    email_linking: bool,
    role_ids: tuple[uuid.UUID, ...] = (),
) -> OidcProviderConfig:
    return OidcProviderConfig(
        id=uuid.uuid4(),
        key="authentik",
        name="Authentik",
        enabled=True,
        issuer="https://id.example.com",
        client_id="zero-nvr",
        secret_ref=None,
        auto_provision=auto_provision,
        email_linking=email_linking,
        default_role_ids=role_ids,
    )


def test_oidc_auto_provision_reuses_external_identity(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with app.state.database.session() as session:
        role = Role(
            name="OIDC Viewer",
            description="test",
            built_in=False,
        )
        session.add(role)
        session.flush()

        configured = provider(
            auto_provision=True,
            email_linking=False,
            role_ids=(role.id,),
        )
        claims = {
            "iss": "https://id.example.com",
            "sub": "subject-123",
            "email": "sso@example.com",
            "email_verified": True,
            "preferred_username": "sso-user",
            "name": "SSO User",
        }

        first = OidcIdentityService.login(
            session,
            provider=configured,
            claims=claims,
        )
        first_id = first.id
        assert first.username == "sso-user"
        assert [item.name for item in first.roles] == [
            "OIDC Viewer"
        ]

        second = OidcIdentityService.login(
            session,
            provider=configured,
            claims={
                **claims,
                "name": "Renamed upstream",
            },
        )
        assert second.id == first_id
        session.commit()

        assert session.scalar(
            select(func.count())
            .select_from(User)
        ) == 1
        assert session.scalar(
            select(func.count())
            .select_from(ExternalIdentity)
        ) == 1


def test_oidc_email_linking_requires_verified_email(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with app.state.database.session() as session:
        local = User(
            username="local-user",
            display_name="Local User",
            email="link@example.com",
            password_hash=None,
            enabled=True,
        )
        session.add(local)
        session.flush()

        configured = provider(
            auto_provision=False,
            email_linking=True,
        )

        with pytest.raises(ApiError) as exc_info:
            OidcIdentityService.login(
                session,
                provider=configured,
                claims={
                    "sub": "unverified",
                    "email": "link@example.com",
                    "email_verified": False,
                },
            )
        assert (
            exc_info.value.code
            == "oidc_identity_unlinked"
        )

        linked = OidcIdentityService.login(
            session,
            provider=configured,
            claims={
                "sub": "verified",
                "email": "link@example.com",
                "email_verified": True,
            },
        )
        assert linked.id == local.id
        session.commit()

        identity = session.scalar(
            select(ExternalIdentity)
        )
        assert identity is not None
        assert identity.user_id == local.id


def test_oidc_rejects_issuer_mismatch_and_missing_role(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with app.state.database.session() as session:
        configured = provider(
            auto_provision=True,
            email_linking=False,
            role_ids=(uuid.uuid4(),),
        )

        with pytest.raises(ApiError) as issuer_error:
            OidcIdentityService.login(
                session,
                provider=configured,
                claims={
                    "iss": "https://other.example.com",
                    "sub": "subject",
                },
            )
        assert (
            issuer_error.value.code
            == "oidc_issuer_mismatch"
        )

        with pytest.raises(ApiError) as role_error:
            OidcIdentityService.login(
                session,
                provider=configured,
                claims={
                    "iss": configured.issuer,
                    "sub": "subject",
                },
            )
        assert (
            role_error.value.code
            == "oidc_default_role_unavailable"
        )



def test_oidc_auto_provision_does_not_trust_unverified_email(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with app.state.database.session() as session:
        role = Role(
            name="OIDC Limited",
            description="test",
            built_in=False,
        )
        session.add(role)
        session.flush()

        configured = provider(
            auto_provision=True,
            email_linking=False,
            role_ids=(role.id,),
        )
        user = OidcIdentityService.login(
            session,
            provider=configured,
            claims={
                "iss": configured.issuer,
                "sub": "unverified-auto",
                "email": "unverified@example.com",
                "email_verified": False,
                "preferred_username": "unverified-user",
            },
        )
        assert user.email is None

        identity = session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.subject
                == "unverified-auto"
            )
        )
        assert identity is not None
        assert identity.email == "unverified@example.com"
