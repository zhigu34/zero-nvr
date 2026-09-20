from __future__ import annotations

from collections.abc import Callable
import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError

from .camera_scope import CameraScopeService, EffectiveCameraScope
from .service import AuthContext, AuthService


def get_auth_context(
    request: Request,
    session: Session = Depends(get_db_session),
) -> AuthContext:
    settings = request.app.state.settings
    authorization = (
        request.headers.get("authorization") or ""
    ).strip()
    service = AuthService(settings)
    if authorization:
        scheme, separator, credential = (
            authorization.partition(" ")
        )
        if (
            separator
            and scheme.lower() == "bearer"
            and credential.strip()
        ):
            context = service.resolve_api_token(
                session,
                credential.strip(),
            )
        else:
            raise ApiError(
                status_code=401,
                code="authentication_required",
                message="Authentication is required.",
            )
    else:
        token = request.cookies.get(
            settings.session_cookie_name
        )
        context = service.resolve_session(
            session,
            token,
        )
    # Authentication reads must not leave a DB transaction open while an
    # endpoint later performs ONVIF/ZLM/rclone/FFmpeg/network work.
    session.commit()
    return context


def require_permission(permission: str) -> Callable[..., AuthContext]:
    def dependency(
        context: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        if permission not in context.permissions:
            raise ApiError(
                status_code=403,
                code="permission_denied",
                message="You do not have permission to perform this action.",
                details={"permission": permission},
            )
        return context

    return dependency


def get_effective_camera_scope(
    context: AuthContext,
    session: Session,
) -> EffectiveCameraScope:
    return CameraScopeService.effective_scope(
        session,
        user_id=context.user.id,
        role_ids=[role.id for role in context.user.roles],
    )


def require_camera_permission(permission: str) -> Callable[..., AuthContext]:
    def dependency(
        camera_id: uuid.UUID,
        context: AuthContext = Depends(get_auth_context),
        session: Session = Depends(get_db_session),
    ) -> AuthContext:
        if permission not in context.permissions:
            raise ApiError(
                status_code=403,
                code="permission_denied",
                message="You do not have permission to perform this action.",
                details={"permission": permission},
            )

        scope = get_effective_camera_scope(context, session)
        session.commit()
        if not scope.allows(camera_id):
            raise ApiError(
                status_code=404,
                code="camera_not_found",
                message="Camera was not found.",
            )
        return context

    return dependency



def require_interactive_session(
    context: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    if context.session is None:
        raise ApiError(
            status_code=403,
            code="interactive_session_required",
            message="An interactive browser session is required.",
        )
    return context
