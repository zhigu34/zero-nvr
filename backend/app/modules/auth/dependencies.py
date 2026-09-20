from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError

from .service import AuthContext, AuthService


def get_auth_context(
    request: Request,
    session: Session = Depends(get_db_session),
) -> AuthContext:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    return AuthService(settings).resolve_session(session, token)


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
