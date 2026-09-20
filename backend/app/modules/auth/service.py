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

from .models import Role, RolePermission, User, UserSession
from .permissions import BUILTIN_ROLE_PERMISSIONS
from .security import PasswordService, SessionSigner


BOOTSTRAP_NAMESPACE = "bootstrap.initial_admin"


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    session: UserSession
    roles: tuple[str, ...]
    permissions: frozenset[str]


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.passwords = PasswordService()
        self.signer = SessionSigner(settings.secret_key)

    @staticmethod
    def setup_required(session: Session) -> bool:
        user_count = session.scalar(select(func.count()).select_from(User))
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
            for permission in desired_permissions - current.keys():
                role.permissions.append(RolePermission(permission=permission))
            for permission in current.keys() - desired_permissions:
                session.delete(current[permission])

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
        if (
            user is None
            or not user.enabled
            or not user.password_hash
            or not self.passwords.verify(password, user.password_hash)
        ):
            raise ApiError(
                status_code=401,
                code="invalid_credentials",
                message="Invalid username or password.",
            )
        return user

    def create_session(self, session: Session, user: User) -> tuple[UserSession, str]:
        now = utc_now()
        expires_at = now + timedelta(hours=self.settings.session_ttl_hours)
        user_session = UserSession(
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
            client_info=None,
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

        roles = tuple(sorted(role.name for role in user.roles))
        permissions = frozenset(
            permission.permission
            for role in user.roles
            for permission in role.permissions
        )
        return AuthContext(
            user=user,
            session=user_session,
            roles=roles,
            permissions=permissions,
        )

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
