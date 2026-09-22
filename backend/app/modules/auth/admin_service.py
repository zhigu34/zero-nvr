from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db.types import utc_now
from app.core.errors import ApiError

from .camera_scope import CameraScopeService
from .models import Role, RolePermission, User, UserSession
from .permissions import ALL_PERMISSIONS
from .security import PasswordService


ADMIN_ROLE_NAME = "Administrator"


class AuthAdminService:
    def __init__(self, settings: Settings) -> None:
        self.passwords = PasswordService()

    @staticmethod
    def list_users(session: Session) -> list[User]:
        return list(session.scalars(select(User).order_by(User.username)))

    @staticmethod
    def get_user(session: Session, user_id: uuid.UUID) -> User:
        user = session.get(User, user_id)
        if user is None:
            raise ApiError(
                status_code=404,
                code="user_not_found",
                message="User was not found.",
            )
        return user

    @staticmethod
    def list_roles(session: Session) -> list[Role]:
        return list(session.scalars(select(Role).order_by(Role.name)))

    @staticmethod
    def get_role(session: Session, role_id: uuid.UUID) -> Role:
        role = session.get(Role, role_id)
        if role is None:
            raise ApiError(
                status_code=404,
                code="role_not_found",
                message="Role was not found.",
            )
        return role

    @staticmethod
    def _roles_by_ids(
        session: Session,
        role_ids: list[uuid.UUID],
    ) -> list[Role]:
        unique_ids = set(role_ids)
        if not unique_ids:
            return []

        roles = list(
            session.scalars(
                select(Role).where(Role.id.in_(unique_ids))
            )
        )
        found = {role.id for role in roles}
        missing = unique_ids - found
        if missing:
            raise ApiError(
                status_code=400,
                code="invalid_role_ids",
                message="One or more roles do not exist.",
                details={"role_ids": sorted(str(item) for item in missing)},
            )
        return roles

    @staticmethod
    def _validate_permissions(permissions: list[str]) -> list[str]:
        normalized = sorted(set(permissions))
        unknown = set(normalized) - ALL_PERMISSIONS
        if unknown:
            raise ApiError(
                status_code=400,
                code="invalid_permissions",
                message="One or more permissions are not supported.",
                details={"permissions": sorted(unknown)},
            )
        return normalized

    @staticmethod
    def _has_admin_role(user: User) -> bool:
        return any(role.name == ADMIN_ROLE_NAME for role in user.roles)

    @staticmethod
    def _enabled_admin_count(session: Session) -> int:
        count = session.scalar(
            select(func.count(func.distinct(User.id)))
            .join(User.roles)
            .where(
                User.enabled.is_(True),
                Role.name == ADMIN_ROLE_NAME,
            )
        )
        return int(count or 0)

    @classmethod
    def _guard_last_administrator(
        cls,
        session: Session,
        user: User,
    ) -> None:
        if (
            user.enabled
            and cls._has_admin_role(user)
            and cls._enabled_admin_count(session) <= 1
        ):
            raise ApiError(
                status_code=409,
                code="last_administrator",
                message="The last enabled Administrator cannot be removed or disabled.",
            )

    def create_user(
        self,
        session: Session,
        *,
        username: str,
        display_name: str,
        email: str | None,
        password: str,
        role_ids: list[uuid.UUID],
    ) -> User:
        roles = self._roles_by_ids(session, role_ids)
        normalized_email = (
            email.strip().lower()
            if email
            else None
        )
        user = User(
            username=username,
            display_name=display_name,
            email=normalized_email,
            password_hash=self.passwords.hash(password),
            enabled=True,
        )
        user.roles = roles
        session.add(user)
        try:
            session.flush()
        except IntegrityError as exc:
            raise ApiError(
                status_code=409,
                code="username_conflict",
                message="Username already exists.",
            ) from exc
        return user

    def update_user(
        self,
        session: Session,
        *,
        user: User,
        changes: dict[str, Any],
    ) -> User:
        if "display_name" in changes:
            user.display_name = str(changes["display_name"])

        if "email" in changes:
            raw_email = changes["email"]
            normalized_email = (
                str(raw_email).strip().lower()
                if raw_email is not None
                else None
            )
            if normalized_email != user.email:
                user.email = normalized_email
                user.email_verified_at = None

        if "role_ids" in changes:
            roles = self._roles_by_ids(session, list(changes["role_ids"] or []))
            keeps_admin = any(role.name == ADMIN_ROLE_NAME for role in roles)
            if self._has_admin_role(user) and not keeps_admin:
                self._guard_last_administrator(session, user)
            user.roles = roles

        session.flush()
        return user

    def reset_user_password(
        self,
        session: Session,
        *,
        user: User,
        new_password: str,
    ) -> User:
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
        session.flush()
        return user

    @classmethod
    def disable_user(
        cls,
        session: Session,
        *,
        user: User,
    ) -> User:
        if not user.enabled:
            return user

        cls._guard_last_administrator(session, user)
        user.enabled = False
        now = utc_now()
        active_sessions = session.scalars(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
        ).all()
        for user_session in active_sessions:
            user_session.revoked_at = now
        session.flush()
        return user

    @staticmethod
    def enable_user(
        session: Session,
        *,
        user: User,
    ) -> User:
        user.enabled = True
        session.flush()
        return user

    @classmethod
    def create_role(
        cls,
        session: Session,
        *,
        name: str,
        description: str | None,
        permissions: list[str],
    ) -> Role:
        normalized = cls._validate_permissions(permissions)
        role = Role(
            name=name,
            description=description,
            built_in=False,
        )
        role.permissions = [
            RolePermission(permission=permission)
            for permission in normalized
        ]
        session.add(role)
        try:
            session.flush()
            CameraScopeService.ensure_scope(
                session,
                principal_type="role",
                principal_id=role.id,
                mode="none",
            )
        except IntegrityError as exc:
            raise ApiError(
                status_code=409,
                code="role_name_conflict",
                message="Role name already exists.",
            ) from exc
        return role

    @classmethod
    def update_role(
        cls,
        session: Session,
        *,
        role: Role,
        changes: dict[str, Any],
    ) -> Role:
        if role.built_in:
            raise ApiError(
                status_code=409,
                code="builtin_role_immutable",
                message="Built-in roles cannot be modified.",
            )

        if "name" in changes and changes["name"] is not None:
            role.name = str(changes["name"])

        if "description" in changes:
            role.description = changes["description"]

        if "permissions" in changes and changes["permissions"] is not None:
            normalized = cls._validate_permissions(list(changes["permissions"]))
            existing = {item.permission: item for item in role.permissions}
            desired = set(normalized)

            for permission in desired - set(existing):
                role.permissions.append(RolePermission(permission=permission))
            for permission in set(existing) - desired:
                session.delete(existing[permission])

        try:
            session.flush()
        except IntegrityError as exc:
            raise ApiError(
                status_code=409,
                code="role_name_conflict",
                message="Role name already exists.",
            ) from exc
        return role
