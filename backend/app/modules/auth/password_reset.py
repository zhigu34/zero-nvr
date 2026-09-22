from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.modules.notifications.models import NotificationDelivery
from app.modules.notifications.service import NotificationTargetService

from .models import PasswordResetToken, User, UserSession
from .security import PasswordService


_RESET_CONTEXT = b"zero-nvr/password-reset/v1:"
_RESET_TTL = timedelta(minutes=30)
_REQUEST_THROTTLE = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class PasswordResetIssue:
    user_id: uuid.UUID
    delivery_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class AdminPasswordResetIssue:
    user_id: uuid.UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PasswordResetMail:
    recipient: str
    title: str
    body: str


class PasswordResetService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.passwords = PasswordService()

    @staticmethod
    def _b64(value: bytes) -> str:
        return (
            base64.urlsafe_b64encode(value)
            .rstrip(b"=")
            .decode("ascii")
        )

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    @classmethod
    def _token_for_key(
        cls,
        reset: PasswordResetToken,
        key: str,
    ) -> str:
        expires = int(
            reset.expires_at.astimezone(UTC).timestamp()
        )
        payload = (
            reset.id.bytes
            + reset.user_id.bytes
            + expires.to_bytes(
                8,
                "big",
                signed=True,
            )
        )
        signature = hmac.new(
            key.encode("utf-8"),
            _RESET_CONTEXT + payload,
            hashlib.sha256,
        ).digest()
        return (
            "znr1."
            + cls._b64(reset.id.bytes)
            + "."
            + cls._b64(signature)
        )

    def _key_values(self) -> tuple[str, ...]:
        values = [
            self.settings.secret_key.get_secret_value()
        ]
        values.extend(
            item.get_secret_value()
            for item in self.settings.secret_key_previous
        )
        return tuple(values)

    def token_for_record(
        self,
        reset: PasswordResetToken,
    ) -> str:
        for key in self._key_values():
            token = self._token_for_key(
                reset,
                key,
            )
            if hmac.compare_digest(
                self._hash_token(token),
                reset.token_hash,
            ):
                return token
        raise ApiError(
            status_code=409,
            code="password_reset_token_unavailable",
            message="Password reset token can no longer be reconstructed.",
        )

    @staticmethod
    def _invalid_token() -> ApiError:
        return ApiError(
            status_code=400,
            code="password_reset_token_invalid",
            message="Password reset token is invalid or expired.",
        )

    def _create_reset(
        self,
        session: Session,
        *,
        user: User,
        created_by: uuid.UUID | None,
        request_metadata: dict[str, object] | None,
    ) -> PasswordResetToken:
        now = utc_now()
        for item in session.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
        ):
            item.used_at = now

        reset = PasswordResetToken(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash="pending",
            requested_at=now,
            expires_at=now + _RESET_TTL,
            used_at=None,
            request_metadata=request_metadata or None,
            created_by=created_by,
        )
        reset.token_hash = self._hash_token(
            self._token_for_key(
                reset,
                self.settings.secret_key.get_secret_value(),
            )
        )
        session.add(reset)
        session.flush()
        return reset

    def issue_admin(
        self,
        session: Session,
        *,
        user: User,
        created_by: uuid.UUID,
        request_metadata: dict[str, object] | None,
    ) -> AdminPasswordResetIssue:
        if not user.enabled:
            raise ApiError(
                status_code=409,
                code="user_disabled",
                message="Disabled user must be enabled before password reset.",
            )
        reset = self._create_reset(
            session,
            user=user,
            created_by=created_by,
            request_metadata=request_metadata,
        )
        return AdminPasswordResetIssue(
            user_id=user.id,
            token=self.token_for_record(reset),
            expires_at=reset.expires_at,
        )

    def issue(
        self,
        session: Session,
        *,
        identifier: str,
        request_metadata: dict[str, object] | None,
    ) -> PasswordResetIssue | None:
        normalized = identifier.strip()
        if not normalized:
            return None

        user = session.scalar(
            select(User).where(
                User.enabled.is_(True),
                or_(
                    User.username == normalized,
                    func.lower(User.email)
                    == normalized.lower(),
                ),
            ).limit(1)
        )
        if (
            user is None
            or not user.email
        ):
            return None

        target = NotificationTargetService.security_email_target(
            session
        )
        if target is not None and not target.enabled:
            target = None
        if target is None:
            # Backward-compatible fallback for deployments that still
            # have the pre-structured-SMTP Apprise reset target.
            target = NotificationTargetService.password_reset_target(
                session
            )
        if target is None:
            return None

        now = utc_now()
        recent = session.scalar(
            select(PasswordResetToken.id)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.requested_at
                >= now - _REQUEST_THROTTLE,
            )
            .limit(1)
        )
        if recent is not None:
            return None

        reset = self._create_reset(
            session,
            user=user,
            created_by=None,
            request_metadata=request_metadata,
        )

        delivery = NotificationDelivery(
            alert_id=None,
            purpose="password_reset",
            notification_target_id=target.id,
            state="PENDING",
            attempt_count=0,
            title="zero-nvr password reset",
            body=(
                "A one-time password reset token was requested. "
                "The token is generated only when this message is sent."
            ),
            correlation_id=str(reset.id),
        )
        session.add(delivery)
        session.flush()

        return PasswordResetIssue(
            user_id=user.id,
            delivery_id=delivery.id,
        )

    def delivery_mail(
        self,
        session: Session,
        *,
        correlation_id: str,
    ) -> PasswordResetMail:
        try:
            reset_id = uuid.UUID(correlation_id)
        except ValueError as exc:
            raise ApiError(
                status_code=409,
                code="password_reset_delivery_invalid",
                message="Password reset delivery is invalid.",
            ) from exc

        reset = session.get(
            PasswordResetToken,
            reset_id,
        )
        now = utc_now()
        if (
            reset is None
            or reset.used_at is not None
            or reset.expires_at <= now
        ):
            raise self._invalid_token()

        user = session.get(User, reset.user_id)
        if (
            user is None
            or not user.enabled
            or not user.email
        ):
            raise self._invalid_token()

        token = self.token_for_record(reset)
        expires = (
            reset.expires_at.astimezone(UTC)
            .strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        return PasswordResetMail(
            recipient=user.email,
            title="zero-nvr password reset",
            body=(
                "A password reset was requested for your zero-nvr account.\n\n"
                "One-time reset token:\n"
                f"{token}\n\n"
                f"This token expires at {expires}.\n"
                "Open zero-nvr, choose Forgot password, then paste the token.\n\n"
                "If you did not request this reset, you can ignore this message."
            ),
        )

    def consume(
        self,
        session: Session,
        *,
        token: str,
        new_password: str,
    ) -> User:
        normalized = token.strip()
        if not normalized:
            raise self._invalid_token()

        reset = session.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash
                == self._hash_token(normalized)
            )
        )
        now = utc_now()
        if (
            reset is None
            or reset.used_at is not None
            or reset.expires_at <= now
        ):
            raise self._invalid_token()

        user = session.get(User, reset.user_id)
        if user is None or not user.enabled:
            raise self._invalid_token()

        user.password_hash = self.passwords.hash(
            new_password
        )

        for user_session in session.scalars(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
        ):
            user_session.revoked_at = now

        for item in session.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        ):
            item.used_at = now

        session.flush()
        return user
