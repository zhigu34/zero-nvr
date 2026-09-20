from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security.passwords import (
    PasswordPolicyError,
    PasswordService,
)

from .models import ExportJob, ExportShareToken


@dataclass(frozen=True, slots=True)
class CreatedShare:
    share: ExportShareToken
    token: str


@dataclass(frozen=True, slots=True)
class AuthorizedShareDownload:
    share_id: uuid.UUID
    export: ExportJob


class ExportShareService:
    max_lifetime = timedelta(days=30)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        export: ExportJob,
        created_by: uuid.UUID,
        password: str | None,
        expires_in_hours: int,
        max_downloads: int | None,
    ) -> CreatedShare:
        if export.state != "COMPLETED":
            raise ApiError(
                status_code=409,
                code="export_not_ready",
                message="Only completed exports can be shared.",
            )
        if expires_in_hours < 1 or expires_in_hours > 24 * 30:
            raise ApiError(
                status_code=400,
                code="export_share_expiry_invalid",
                message="Share expiry must be between 1 hour and 30 days.",
            )
        if (
            max_downloads is not None
            and (max_downloads < 1 or max_downloads > 100000)
        ):
            raise ApiError(
                status_code=400,
                code="export_share_download_limit_invalid",
                message="Share download limit is invalid.",
            )

        password_hash: str | None = None
        if password is not None:
            try:
                password_hash = PasswordService().hash_password(
                    password
                )
            except PasswordPolicyError as exc:
                raise ApiError(
                    status_code=400,
                    code="export_share_password_invalid",
                    message="Share password does not meet password policy.",
                ) from exc

        token = secrets.token_urlsafe(32)
        share = ExportShareToken(
            export_id=export.id,
            token_hash=cls._token_hash(token),
            password_hash=password_hash,
            expires_at=min(
                export.expires_at,
                datetime.now(UTC)
                + timedelta(hours=expires_in_hours),
            ),
            max_downloads=max_downloads,
            download_count=0,
            created_by=created_by,
        )
        session.add(share)
        session.flush()
        return CreatedShare(
            share=share,
            token=token,
        )

    @staticmethod
    def list_for_export(
        session: Session,
        *,
        export_id: uuid.UUID,
    ) -> list[ExportShareToken]:
        return list(
            session.scalars(
                select(ExportShareToken)
                .where(
                    ExportShareToken.export_id
                    == export_id
                )
                .order_by(
                    ExportShareToken.created_at.desc(),
                    ExportShareToken.id.desc(),
                )
            )
        )

    @staticmethod
    def revoke(
        session: Session,
        *,
        share: ExportShareToken,
    ) -> ExportShareToken:
        if share.revoked_at is None:
            share.revoked_at = datetime.now(UTC)
            session.flush()
        return share

    @staticmethod
    def get(
        session: Session,
        share_id: uuid.UUID,
    ) -> ExportShareToken:
        share = session.get(
            ExportShareToken,
            share_id,
        )
        if share is None:
            raise ApiError(
                status_code=404,
                code="export_share_not_found",
                message="Export share was not found.",
            )
        return share

    @classmethod
    def authorize_download(
        cls,
        session: Session,
        *,
        token: str,
        password: str | None,
    ) -> AuthorizedShareDownload:
        share = session.scalar(
            select(ExportShareToken).where(
                ExportShareToken.token_hash
                == cls._token_hash(token)
            )
        )
        if share is None:
            raise ApiError(
                status_code=404,
                code="export_share_not_found",
                message="Export share was not found.",
            )

        now = datetime.now(UTC)
        if (
            share.revoked_at is not None
            or share.expires_at <= now
        ):
            raise ApiError(
                status_code=410,
                code="export_share_expired",
                message="Export share is no longer available.",
            )
        if (
            share.max_downloads is not None
            and share.download_count
            >= share.max_downloads
        ):
            raise ApiError(
                status_code=410,
                code="export_share_download_limit_reached",
                message="Export share download limit has been reached.",
            )

        if share.password_hash is not None:
            if (
                password is None
                or not PasswordService().verify_password(
                    password,
                    share.password_hash,
                )
            ):
                raise ApiError(
                    status_code=401,
                    code="export_share_password_required",
                    message="A valid share password is required.",
                )

        export = session.get(
            ExportJob,
            share.export_id,
        )
        if (
            export is None
            or export.state != "COMPLETED"
            or export.expires_at <= now
        ):
            raise ApiError(
                status_code=410,
                code="export_share_unavailable",
                message="Shared export is no longer available.",
            )

        return AuthorizedShareDownload(
            share_id=share.id,
            export=export,
        )

    @staticmethod
    def consume_download(
        session: Session,
        *,
        share_id: uuid.UUID,
    ) -> None:
        now = datetime.now(UTC)
        result = session.execute(
            update(ExportShareToken)
            .where(
                ExportShareToken.id == share_id,
                ExportShareToken.revoked_at.is_(None),
                ExportShareToken.expires_at > now,
                or_(
                    ExportShareToken.max_downloads.is_(None),
                    ExportShareToken.download_count
                    < ExportShareToken.max_downloads,
                ),
            )
            .values(
                download_count=ExportShareToken.download_count + 1,
                last_download_at=now,
            )
        )
        if result.rowcount != 1:
            raise ApiError(
                status_code=410,
                code="export_share_download_limit_reached",
                message="Export share is no longer available.",
            )
        session.flush()
