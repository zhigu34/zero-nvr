from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.modules.audit.service import append_audit_event

from .admin_service import AuthAdminService
from .camera_scope import CameraScopeService, CameraScopeValue
from .dependencies import require_permission
from .models import Role, User
from .oidc import (
    OidcProviderConfig,
    OidcProviderSettingsService,
)
from .password_reset import PasswordResetService
from .permissions import ALL_PERMISSIONS
from .schemas import (
    CameraScopeUpdate,
    CameraScopeView,
    OidcProviderCreate,
    OidcProviderUpdate,
    OidcProviderView,
    RoleCreate,
    RoleSummary,
    RoleUpdate,
    RoleView,
    UserAdminView,
    UserCreate,
    UserPasswordResetIssue,
    UserUpdate,
)
from .service import AuthContext


router = APIRouter()


def _role_summary(role: Role) -> RoleSummary:
    return RoleSummary(
        id=role.id,
        name=role.name,
        description=role.description,
        built_in=role.built_in,
    )


def _role_view(role: Role) -> RoleView:
    return RoleView(
        id=role.id,
        name=role.name,
        description=role.description,
        built_in=role.built_in,
        permissions=sorted(item.permission for item in role.permissions),
    )


def _user_view(user: User) -> UserAdminView:
    return UserAdminView(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        enabled=user.enabled,
        roles=sorted(
            (_role_summary(role) for role in user.roles),
            key=lambda item: item.name,
        ),
    )


def _user_audit_snapshot(user: User) -> dict[str, Any]:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "enabled": user.enabled,
        "roles": sorted(role.name for role in user.roles),
    }


def _scope_view(value: CameraScopeValue | None) -> CameraScopeView:
    if value is None:
        return CameraScopeView(mode="inherit")
    return CameraScopeView(
        mode=value.mode,
        camera_ids=list(value.camera_ids),
        camera_group_ids=list(value.camera_group_ids),
    )


def _scope_audit_snapshot(value: CameraScopeView) -> dict[str, Any]:
    return {
        "mode": value.mode,
        "camera_ids": sorted(str(item) for item in value.camera_ids),
        "camera_group_ids": sorted(
            str(item) for item in value.camera_group_ids
        ),
    }


def _role_audit_snapshot(role: Role) -> dict[str, Any]:
    return {
        "name": role.name,
        "description": role.description,
        "built_in": role.built_in,
        "permissions": sorted(item.permission for item in role.permissions),
    }


@router.get("/users", response_model=list[UserAdminView])
def list_users(
    _context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> list[UserAdminView]:
    return [
        _user_view(user)
        for user in AuthAdminService.list_users(session)
    ]


@router.post("/users", response_model=UserAdminView, status_code=201)
def create_user(
    body: UserCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> UserAdminView:
    service = AuthAdminService(request.app.state.settings)
    try:
        user = service.create_user(
            session,
            username=body.username,
            display_name=body.display_name,
            email=str(body.email) if body.email else None,
            password=body.password,
            role_ids=body.role_ids,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="user.create",
            resource_type="user",
            resource_id=user.id,
            after=_user_audit_snapshot(user),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _user_view(user)


@router.get("/users/{user_id}", response_model=UserAdminView)
def get_user(
    user_id: uuid.UUID,
    _context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> UserAdminView:
    return _user_view(AuthAdminService.get_user(session, user_id))


@router.patch("/users/{user_id}", response_model=UserAdminView)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> UserAdminView:
    service = AuthAdminService(request.app.state.settings)
    try:
        user = service.get_user(session, user_id)
        before = _user_audit_snapshot(user)
        user = service.update_user(
            session,
            user=user,
            changes=body.model_dump(exclude_unset=True),
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="user.update",
            resource_type="user",
            resource_id=user.id,
            before=before,
            after=_user_audit_snapshot(user),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _user_view(user)


@router.post(
    "/users/{user_id}/password-reset",
    response_model=UserPasswordResetIssue,
)
def issue_user_password_reset(
    user_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("user.manage")
    ),
    session: Session = Depends(get_db_session),
) -> UserPasswordResetIssue:
    service = PasswordResetService(
        request.app.state.settings
    )
    try:
        user = AuthAdminService.get_user(
            session,
            user_id,
        )
        issued = service.issue_admin(
            session,
            user=user,
            created_by=context.user.id,
            request_metadata={
                "source": "administrator",
            },
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="user.password_reset.issue",
            resource_type="user",
            resource_id=user.id,
            metadata={
                "expires_at": issued.expires_at.isoformat(),
                "single_use": True,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return UserPasswordResetIssue(
        token=issued.token,
        expires_at=issued.expires_at,
    )


@router.post("/users/{user_id}/disable", response_model=UserAdminView)
def disable_user(
    user_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> UserAdminView:
    try:
        user = AuthAdminService.get_user(session, user_id)
        before = _user_audit_snapshot(user)
        user = AuthAdminService.disable_user(session, user=user)
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="user.disable",
            resource_type="user",
            resource_id=user.id,
            before=before,
            after=_user_audit_snapshot(user),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _user_view(user)


@router.post("/users/{user_id}/enable", response_model=UserAdminView)
def enable_user(
    user_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> UserAdminView:
    try:
        user = AuthAdminService.get_user(session, user_id)
        before = _user_audit_snapshot(user)
        user = AuthAdminService.enable_user(session, user=user)
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="user.enable",
            resource_type="user",
            resource_id=user.id,
            before=before,
            after=_user_audit_snapshot(user),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _user_view(user)


@router.get("/permissions", response_model=list[str])
def list_permissions(
    _context: AuthContext = Depends(require_permission("user.manage")),
) -> list[str]:
    return sorted(ALL_PERMISSIONS)


@router.get("/roles", response_model=list[RoleView])
def list_roles(
    _context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> list[RoleView]:
    return [
        _role_view(role)
        for role in AuthAdminService.list_roles(session)
    ]


@router.post("/roles", response_model=RoleView, status_code=201)
def create_role(
    body: RoleCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> RoleView:
    try:
        role = AuthAdminService.create_role(
            session,
            name=body.name,
            description=body.description,
            permissions=body.permissions,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="role.create",
            resource_type="role",
            resource_id=role.id,
            after=_role_audit_snapshot(role),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _role_view(role)


@router.get("/roles/{role_id}", response_model=RoleView)
def get_role(
    role_id: uuid.UUID,
    _context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> RoleView:
    return _role_view(AuthAdminService.get_role(session, role_id))


@router.patch("/roles/{role_id}", response_model=RoleView)
def update_role(
    role_id: uuid.UUID,
    body: RoleUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> RoleView:
    try:
        role = AuthAdminService.get_role(session, role_id)
        before = _role_audit_snapshot(role)
        role = AuthAdminService.update_role(
            session,
            role=role,
            changes=body.model_dump(exclude_unset=True),
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="role.update",
            resource_type="role",
            resource_id=role.id,
            before=before,
            after=_role_audit_snapshot(role),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _role_view(role)


@router.get(
    "/users/{user_id}/camera-scope",
    response_model=CameraScopeView,
)
def get_user_camera_scope(
    user_id: uuid.UUID,
    _context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> CameraScopeView:
    AuthAdminService.get_user(session, user_id)
    value = CameraScopeService.get_scope(
        session,
        principal_type="user",
        principal_id=user_id,
    )
    return _scope_view(value)


@router.put(
    "/users/{user_id}/camera-scope",
    response_model=CameraScopeView,
)
def set_user_camera_scope(
    user_id: uuid.UUID,
    body: CameraScopeUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> CameraScopeView:
    AuthAdminService.get_user(session, user_id)
    before = _scope_view(
        CameraScopeService.get_scope(
            session,
            principal_type="user",
            principal_id=user_id,
        )
    )

    try:
        if body.mode == "inherit":
            if body.camera_ids or body.camera_group_ids:
                from app.core.errors import ApiError
                raise ApiError(
                    status_code=400,
                    code="camera_scope_entries_not_allowed",
                    message="Inherited scope cannot contain explicit entries.",
                )
            CameraScopeService.clear_scope(
                session,
                principal_type="user",
                principal_id=user_id,
            )
            after = CameraScopeView(mode="inherit")
        else:
            value = CameraScopeService.set_scope(
                session,
                principal_type="user",
                principal_id=user_id,
                mode=body.mode,
                camera_ids=body.camera_ids,
                camera_group_ids=body.camera_group_ids,
            )
            after = _scope_view(value)

        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="user.camera_scope.update",
            resource_type="user",
            resource_id=user_id,
            before=_scope_audit_snapshot(before),
            after=_scope_audit_snapshot(after),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return after


@router.get(
    "/roles/{role_id}/camera-scope",
    response_model=CameraScopeView,
)
def get_role_camera_scope(
    role_id: uuid.UUID,
    _context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> CameraScopeView:
    AuthAdminService.get_role(session, role_id)
    value = CameraScopeService.get_scope(
        session,
        principal_type="role",
        principal_id=role_id,
    )
    return _scope_view(value)


@router.put(
    "/roles/{role_id}/camera-scope",
    response_model=CameraScopeView,
)
def set_role_camera_scope(
    role_id: uuid.UUID,
    body: CameraScopeUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> CameraScopeView:
    AuthAdminService.get_role(session, role_id)
    if body.mode == "inherit":
        from app.core.errors import ApiError
        raise ApiError(
            status_code=400,
            code="role_camera_scope_cannot_inherit",
            message="Role camera scope must be all, selected, or none.",
        )

    before = _scope_view(
        CameraScopeService.get_scope(
            session,
            principal_type="role",
            principal_id=role_id,
        )
    )
    try:
        value = CameraScopeService.set_scope(
            session,
            principal_type="role",
            principal_id=role_id,
            mode=body.mode,
            camera_ids=body.camera_ids,
            camera_group_ids=body.camera_group_ids,
        )
        after = _scope_view(value)
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="role.camera_scope.update",
            resource_type="role",
            resource_id=role_id,
            before=_scope_audit_snapshot(before),
            after=_scope_audit_snapshot(after),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return after



def _oidc_provider_view(
    provider: OidcProviderConfig,
) -> OidcProviderView:
    return OidcProviderView(
        id=provider.id,
        key=provider.key,
        name=provider.name,
        enabled=provider.enabled,
        issuer=provider.issuer,
        client_id=provider.client_id,
        client_secret_configured=(
            provider.secret_ref is not None
        ),
        auto_provision=provider.auto_provision,
        email_linking=provider.email_linking,
        default_role_ids=list(
            provider.default_role_ids
        ),
    )


@router.get(
    "/oidc/providers",
    response_model=list[OidcProviderView],
)
def list_oidc_providers(
    _context: AuthContext = Depends(
        require_permission("user.manage")
    ),
    session: Session = Depends(get_db_session),
) -> list[OidcProviderView]:
    return [
        _oidc_provider_view(item)
        for item in OidcProviderSettingsService.list(
            session
        )
    ]


@router.post(
    "/oidc/providers",
    response_model=OidcProviderView,
    status_code=201,
)
def create_oidc_provider(
    body: OidcProviderCreate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("user.manage")
    ),
    session: Session = Depends(get_db_session),
) -> OidcProviderView:
    service = OidcProviderSettingsService(
        request.app.state.settings
    )
    try:
        provider = service.create(
            session,
            key=body.key,
            name=body.name,
            enabled=body.enabled,
            issuer=body.issuer,
            client_id=body.client_id,
            client_secret=(
                body.client_secret.get_secret_value()
            ),
            auto_provision=body.auto_provision,
            email_linking=body.email_linking,
            default_role_ids=body.default_role_ids,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="oidc_provider.create",
            resource_type="oidc_provider",
            resource_id=provider.id,
            after={
                "key": provider.key,
                "name": provider.name,
                "enabled": provider.enabled,
                "issuer": provider.issuer,
                "client_id": provider.client_id,
                "auto_provision": provider.auto_provision,
                "email_linking": provider.email_linking,
                "default_role_ids": [
                    str(item)
                    for item in provider.default_role_ids
                ],
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _oidc_provider_view(provider)


@router.patch(
    "/oidc/providers/{provider_key}",
    response_model=OidcProviderView,
)
def update_oidc_provider(
    provider_key: str,
    body: OidcProviderUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("user.manage")
    ),
    session: Session = Depends(get_db_session),
) -> OidcProviderView:
    service = OidcProviderSettingsService(
        request.app.state.settings
    )
    try:
        provider = service.get(
            session,
            provider_key,
        )
        changes = body.model_dump(
            exclude_unset=True
        )
        if body.client_secret is not None:
            changes["client_secret"] = (
                body.client_secret.get_secret_value()
            )
        provider = service.update(
            session,
            provider=provider,
            changes=changes,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="oidc_provider.update",
            resource_type="oidc_provider",
            resource_id=provider.id,
            metadata={
                "key": provider.key,
                "secret_replaced": (
                    body.client_secret is not None
                ),
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _oidc_provider_view(provider)


@router.delete(
    "/oidc/providers/{provider_key}",
    status_code=204,
)
def delete_oidc_provider(
    provider_key: str,
    request: Request,
    context: AuthContext = Depends(
        require_permission("user.manage")
    ),
    session: Session = Depends(get_db_session),
) -> None:
    service = OidcProviderSettingsService(
        request.app.state.settings
    )
    try:
        provider = service.get(
            session,
            provider_key,
        )
        service.delete(
            session,
            provider=provider,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="oidc_provider.delete",
            resource_type="oidc_provider",
            resource_id=provider.id,
            before={
                "key": provider.key,
                "name": provider.name,
                "issuer": provider.issuer,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
