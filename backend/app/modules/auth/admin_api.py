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
from .schemas import (
    CameraScopeUpdate,
    CameraScopeView,
    RoleCreate,
    RoleSummary,
    RoleUpdate,
    RoleView,
    UserAdminView,
    UserCreate,
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
