from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db.types import utc_now
from app.core.errors import ApiError

from .models import ExternalIdentity, Role, User
from .oidc import OidcProviderConfig


_USERNAME = re.compile(r"^[A-Za-z0-9_.-]+$")


class OidcIdentityService:
    @staticmethod
    def _text(
        claims: Mapping[str, Any],
        key: str,
    ) -> str | None:
        value = claims.get(key)
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @classmethod
    def _username_base(
        cls,
        claims: Mapping[str, Any],
        *,
        issuer: str,
        subject: str,
    ) -> str:
        email = cls._text(claims, "email")
        candidates = [
            cls._text(
                claims,
                "preferred_username",
            ),
            (
                email.split("@", 1)[0]
                if email
                else None
            ),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            normalized = re.sub(
                r"[^A-Za-z0-9_.-]+",
                "-",
                candidate,
            ).strip(".-_")[:48]
            if (
                normalized
                and _USERNAME.fullmatch(normalized)
            ):
                return normalized

        digest = hashlib.sha256(
            f"{issuer}|{subject}".encode(
                "utf-8"
            )
        ).hexdigest()[:12]
        return f"oidc-{digest}"

    @classmethod
    def _unique_username(
        cls,
        session: Session,
        claims: Mapping[str, Any],
        *,
        issuer: str,
        subject: str,
    ) -> str:
        base = cls._username_base(
            claims,
            issuer=issuer,
            subject=subject,
        )
        candidate = base[:64]
        suffix_index = 1

        while session.scalar(
            select(User.id).where(
                User.username == candidate
            )
        ) is not None:
            suffix_index += 1
            suffix = f"-{suffix_index}"
            candidate = (
                base[: 64 - len(suffix)]
                + suffix
            )
        return candidate

    @staticmethod
    def _default_roles(
        session: Session,
        provider: OidcProviderConfig,
    ) -> list[Role]:
        if not provider.default_role_ids:
            return []

        unique = set(
            provider.default_role_ids
        )
        roles = list(
            session.scalars(
                select(Role).where(
                    Role.id.in_(unique)
                )
            )
        )
        if len(roles) != len(unique):
            raise ApiError(
                status_code=409,
                code="oidc_default_role_unavailable",
                message=(
                    "An OIDC default role no longer exists."
                ),
            )
        return roles

    @classmethod
    def login(
        cls,
        session: Session,
        *,
        provider: OidcProviderConfig,
        claims: Mapping[str, Any],
    ) -> User:
        subject = cls._text(
            claims,
            "sub",
        )
        if not subject:
            raise ApiError(
                status_code=403,
                code="oidc_subject_missing",
                message=(
                    "OIDC identity does not "
                    "contain a subject."
                ),
            )

        claim_issuer = cls._text(
            claims,
            "iss",
        )
        if (
            claim_issuer is not None
            and claim_issuer.rstrip("/")
            != provider.issuer.rstrip("/")
        ):
            raise ApiError(
                status_code=403,
                code="oidc_issuer_mismatch",
                message=(
                    "OIDC issuer does not match "
                    "the configured provider."
                ),
            )

        email = cls._text(
            claims,
            "email",
        )
        email_verified = (
            claims.get("email_verified")
            is True
        )
        verified_email = (
            email
            if email_verified
            else None
        )
        now = utc_now()

        identity = session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.issuer
                == provider.issuer,
                ExternalIdentity.subject
                == subject,
            )
        )
        if identity is not None:
            user = session.get(
                User,
                identity.user_id,
            )
            if (
                user is None
                or not user.enabled
            ):
                raise ApiError(
                    status_code=403,
                    code="oidc_user_disabled",
                    message="OIDC user is disabled.",
                )
            identity.email = email
            identity.last_login_at = now
            user.last_login_at = now
            session.flush()
            return user

        user: User | None = None
        if (
            provider.email_linking
            and email_verified
            and email
        ):
            matches = list(
                session.scalars(
                    select(User).where(
                        func.lower(User.email)
                        == email.lower(),
                        User.enabled.is_(True),
                    )
                )
            )
            if len(matches) > 1:
                raise ApiError(
                    status_code=409,
                    code="oidc_email_ambiguous",
                    message=(
                        "OIDC email matches "
                        "multiple local users."
                    ),
                )
            if matches:
                user = matches[0]

        if (
            user is None
            and provider.auto_provision
        ):
            roles = cls._default_roles(
                session,
                provider,
            )
            username = cls._unique_username(
                session,
                claims,
                issuer=provider.issuer,
                subject=subject,
            )
            display_name = (
                cls._text(claims, "name")
                or cls._text(
                    claims,
                    "preferred_username",
                )
                or email
                or username
            )[:128]
            user = User(
                username=username,
                display_name=display_name,
                email=verified_email,
                password_hash=None,
                enabled=True,
            )
            user.roles = roles
            user.last_login_at = now
            session.add(user)
            session.flush()

        if user is None:
            raise ApiError(
                status_code=403,
                code="oidc_identity_unlinked",
                message=(
                    "OIDC identity is not linked "
                    "to a zero-nvr user."
                ),
            )

        identity = ExternalIdentity(
            user_id=user.id,
            issuer=provider.issuer,
            subject=subject,
            email=email,
            last_login_at=now,
        )
        session.add(identity)
        user.last_login_at = now
        session.flush()
        return user
