from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.types import utc_now
from app.core.errors import ApiError

from .models import PersonalApiToken


_TOKEN_PREFIX = "znr_pat_"


@dataclass(frozen=True, slots=True)
class CreatedPersonalApiToken:
    record: PersonalApiToken
    plaintext: str


class PersonalApiTokenService:
    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    @classmethod
    def resolve(
        cls,
        session: Session,
        *,
        plaintext: str,
    ) -> PersonalApiToken:
        token = plaintext.strip()
        if not token.startswith(_TOKEN_PREFIX):
            raise ApiError(
                status_code=401,
                code="authentication_required",
                message="Authentication is required.",
            )

        record = session.scalar(
            select(PersonalApiToken).where(
                PersonalApiToken.token_hash
                == cls.hash_token(token)
            )
        )
        now = utc_now()
        if (
            record is None
            or record.revoked_at is not None
            or (
                record.expires_at is not None
                and record.expires_at <= now
            )
        ):
            raise ApiError(
                status_code=401,
                code="authentication_required",
                message="Authentication is required.",
            )

        record.last_used_at = now
        session.flush()
        return record

    @staticmethod
    def permission_names(
        record: PersonalApiToken,
    ) -> frozenset[str]:
        raw = (record.permission_scope or {}).get(
            "permissions",
            [],
        )
        if not isinstance(raw, list) or not all(
            isinstance(item, str)
            for item in raw
        ):
            return frozenset()
        return frozenset(raw)

    @staticmethod
    def list_owned(
        session: Session,
        *,
        user_id: uuid.UUID,
    ) -> list[PersonalApiToken]:
        return list(
            session.scalars(
                select(PersonalApiToken)
                .where(
                    PersonalApiToken.user_id
                    == user_id
                )
                .order_by(
                    PersonalApiToken.created_at.desc(),
                    PersonalApiToken.id.desc(),
                )
            )
        )

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        user_id: uuid.UUID,
        name: str,
        permissions: frozenset[str],
        allowed_permissions: frozenset[str],
        expires_at: datetime | None,
    ) -> CreatedPersonalApiToken:
        normalized_name = name.strip()
        if not normalized_name:
            raise ApiError(
                status_code=400,
                code="api_token_name_invalid",
                message="API token name is invalid.",
            )

        if permissions - allowed_permissions:
            raise ApiError(
                status_code=403,
                code="api_token_scope_invalid",
                message=(
                    "API token permissions cannot exceed "
                    "the current authentication scope."
                ),
            )

        if expires_at is not None:
            if expires_at.tzinfo is None:
                raise ApiError(
                    status_code=400,
                    code="api_token_expiry_invalid",
                    message="API token expiry must include a timezone.",
                )
            expires_at = expires_at.astimezone(UTC)
            if expires_at <= utc_now():
                raise ApiError(
                    status_code=400,
                    code="api_token_expiry_invalid",
                    message="API token expiry must be in the future.",
                )

        plaintext = (
            _TOKEN_PREFIX
            + secrets.token_urlsafe(32)
        )
        record = PersonalApiToken(
            user_id=user_id,
            name=normalized_name,
            token_hash=cls.hash_token(plaintext),
            permission_scope={
                "permissions": sorted(permissions),
            },
            expires_at=expires_at,
            revoked_at=None,
            last_used_at=None,
        )
        session.add(record)
        session.flush()
        return CreatedPersonalApiToken(
            record=record,
            plaintext=plaintext,
        )

    @staticmethod
    def revoke(
        session: Session,
        *,
        user_id: uuid.UUID,
        token_id: uuid.UUID,
    ) -> PersonalApiToken:
        record = session.get(
            PersonalApiToken,
            token_id,
        )
        if (
            record is None
            or record.user_id != user_id
        ):
            raise ApiError(
                status_code=404,
                code="api_token_not_found",
                message="API token was not found.",
            )
        if record.revoked_at is None:
            record.revoked_at = utc_now()
            session.flush()
        return record
