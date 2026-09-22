from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.modules.system.models import SystemSetting

from .camera_scope import CameraScopeService
from .api_tokens import PersonalApiTokenService
from .models import (
    PersonalApiToken,
    Role,
    RolePermission,
    User,
    UserSession,
)
from .permissions import BUILTIN_ROLE_PERMISSIONS
from .security import PasswordService, SessionSigner


BOOTSTRAP_NAMESPACE = "bootstrap.initial_admin"


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    roles: tuple[str, ...]
    permissions: frozenset[str]
    session: UserSession | None = None
    api_token: PersonalApiToken | None = None


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.passwords = PasswordService()
        self.signer = SessionSigner(settings.secret_key)

    @staticmethod
    def setup_required(session: Session) -> bool:
        bootstrap_claim = session.get(
            SystemSetting,
            BOOTSTRAP_NAMESPACE,
        )
        if bootstrap_claim is not None:
            return False

        user_count = session.scalar(
            select(func.count()).select_from(User)
        )
        return not bool(user_count)

    @staticmethod
    def _ensure_builtin_roles(session: Session) -> dict[str, Role]:
        existing = {
            role.name: role
            for role in session.scalars(
                select(Role).where(Role.name.in_(BUILTIN_ROLE_PERMISSIONS))
            )
        }

        roles: dict[str, Role] = {}
        for name, desired_permissions in BUILTIN_ROLE_PERMISSIONS.items():
            role = existing.get(name)
            if role is None:
                role = Role(
                    name=name,
                    description=f"Built-in {name} role",
                    built_in=True,
                )
                session.add(role)
                session.flush()
            else:
                role.built_in = True

            current = {item.permission: item for item in role.permissions}
            current_permissions = set(current)
            for permission in desired_permissions - current_permissions:
                role.permissions.append(RolePermission(permission=permission))
            for permission in current_permissions - desired_permissions:
                session.delete(current[permission])

            CameraScopeService.ensure_scope(
                session,
                principal_type="role",
                principal_id=role.id,
                mode="all",
            )
            roles[name] = role

        return roles

    def create_initial_administrator(
        self,
        session: Session,
        *,
        username: str,
        display_name: str,
        email: str | None,
        password: str,
    ) -> User:
        if not self.setup_required(session):
            raise ApiError(
                status_code=409,
                code="setup_already_completed",
                message="Initial administrator setup has already been completed.",
            )

        # A unique durable setup claim prevents two concurrent first-run
        # requests from creating separate administrators with different names.
        session.add(
            SystemSetting(
                namespace=BOOTSTRAP_NAMESPACE,
                value_json={"completed": True},
            )
        )

        try:
            roles = self._ensure_builtin_roles(session)
            user = User(
                username=username,
                display_name=display_name,
                email=email,
                password_hash=self.passwords.hash(password),
                enabled=True,
            )
            user.roles.append(roles["Administrator"])
            session.add(user)
            session.flush()
            return user
        except IntegrityError as exc:
            raise ApiError(
                status_code=409,
                code="setup_already_completed",
                message="Initial administrator setup has already been completed.",
            ) from exc

    def authenticate(
        self,
        session: Session,
        *,
        username: str,
        password: str,
    ) -> User:
        user = session.scalar(select(User).where(User.username == username))
        valid_password = self.passwords.verify_or_dummy(
            password,
            (
                user.password_hash
                if user is not None and user.enabled
                else None
            ),
        )
        if (
            user is None
            or not user.enabled
            or not valid_password
        ):
            raise ApiError(
                status_code=401,
                code="invalid_credentials",
                message="Invalid username or password.",
            )
        return user

    @staticmethod
    def user_roles_and_permissions(
        user: User,
    ) -> tuple[tuple[str, ...], frozenset[str]]:
        roles = tuple(sorted(role.name for role in user.roles))
        permissions = frozenset(
            permission.permission
            for role in user.roles
            for permission in role.permissions
        )
        return roles, permissions

    def create_session(
        self,
        session: Session,
        user: User,
        *,
        client_info: dict[str, object] | None = None,
    ) -> tuple[UserSession, str]:
        now = utc_now()
        expires_at = now + timedelta(hours=self.settings.session_ttl_hours)
        user_session = UserSession(
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
            client_info=client_info,
        )
        session.add(user_session)
        session.flush()
        user.last_login_at = now
        return user_session, self.signer.sign(user_session.id)

    def resolve_session(self, session: Session, token: str | None) -> AuthContext:
        if not token:
            raise self._unauthorized()

        session_id = self.signer.verify(token)
        if session_id is None:
            raise self._unauthorized()

        user_session = session.get(UserSession, session_id)
        now = utc_now()
        if (
            user_session is None
            or user_session.revoked_at is not None
            or user_session.expires_at <= now
        ):
            raise self._unauthorized()

        user = session.get(User, user_session.user_id)
        if user is None or not user.enabled:
            raise self._unauthorized()

        roles, permissions = self.user_roles_and_permissions(user)
        return AuthContext(
            user=user,
            roles=roles,
            permissions=permissions,
            session=user_session,
            api_token=None,
        )

    def resolve_api_token(
        self,
        session: Session,
        token: str,
    ) -> AuthContext:
        record = PersonalApiTokenService.resolve(
            session,
            plaintext=token,
        )
        user = session.get(User, record.user_id)
        if user is None or not user.enabled:
            raise self._unauthorized()

        roles, user_permissions = (
            self.user_roles_and_permissions(user)
        )
        token_permissions = (
            PersonalApiTokenService.permission_names(
                record
            )
        )
        return AuthContext(
            user=user,
            roles=roles,
            permissions=frozenset(
                user_permissions
                & token_permissions
            ),
            session=None,
            api_token=record,
        )

    def change_password(
        self,
        session: Session,
        *,
        context: AuthContext,
        current_password: str,
        new_password: str,
        client_info: dict[str, object] | None = None,
    ) -> tuple[UserSession, str]:
        user = context.user
        if (
            not user.password_hash
            or not self.passwords.verify(current_password, user.password_hash)
        ):
            raise ApiError(
                status_code=400,
                code="invalid_current_password",
                message="Current password is incorrect.",
            )

        user.password_hash = self.passwords.hash(new_password)
        now = utc_now()

        active_sessions = session.scalars(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
        ).all()
        for user_session in active_sessions:
            user_session.revoked_at = now

        return self.create_session(
            session,
            user,
            client_info=client_info,
        )

    @staticmethod
    def list_active_sessions(
        session: Session,
        *,
        user_id: uuid.UUID,
    ) -> list[UserSession]:
        now = utc_now()
        return list(
            session.scalars(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
                .order_by(UserSession.created_at.desc())
            )
        )

    @staticmethod
    def revoke_owned_session(
        session: Session,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> UserSession:
        user_session = session.get(UserSession, session_id)
        if user_session is None or user_session.user_id != user_id:
            raise ApiError(
                status_code=404,
                code="session_not_found",
                message="Session was not found.",
            )

        if user_session.revoked_at is None:
            user_session.revoked_at = utc_now()
        return user_session

    def revoke_session(self, session: Session, token: str | None) -> None:
        if not token:
            return

        session_id = self.signer.verify(token)
        if session_id is None:
            return

        user_session = session.get(UserSession, session_id)
        if user_session is not None and user_session.revoked_at is None:
            user_session.revoked_at = utc_now()

    @staticmethod
    def _unauthorized() -> ApiError:
        return ApiError(
            status_code=401,
            code="authentication_required",
            message="Authentication is required.",
        )
