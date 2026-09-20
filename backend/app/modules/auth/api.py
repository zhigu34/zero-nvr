from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db_session

from .schemas import (
    AuthUser,
    InitialAdministratorCreate,
    LoginRequest,
    SetupStatus,
)
from .service import AuthContext, AuthService


router = APIRouter()


def _service(request: Request) -> AuthService:
    return AuthService(request.app.state.settings)


def _cookie_token(request: Request) -> str | None:
    settings = request.app.state.settings
    return request.cookies.get(settings.session_cookie_name)


def _auth_user(context: AuthContext) -> AuthUser:
    return AuthUser(
        id=context.user.id,
        username=context.user.username,
        display_name=context.user.display_name,
        email=context.user.email,
        roles=list(context.roles),
        permissions=sorted(context.permissions),
    )


@router.get("/setup/status", response_model=SetupStatus)
def setup_status(
    session: Session = Depends(get_db_session),
) -> SetupStatus:
    return SetupStatus(requires_initial_admin=AuthService.setup_required(session))


@router.post("/setup/administrator", response_model=AuthUser, status_code=201)
def create_initial_administrator(
    body: InitialAdministratorCreate,
    request: Request,
    session: Session = Depends(get_db_session),
) -> AuthUser:
    service = _service(request)
    try:
        user = service.create_initial_administrator(
            session,
            username=body.username,
            display_name=body.display_name,
            email=str(body.email) if body.email else None,
            password=body.password,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    roles, permissions = service.user_roles_and_permissions(user)
    return AuthUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        roles=list(roles),
        permissions=sorted(permissions),
    )


@router.post("/auth/login", response_model=AuthUser)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> AuthUser:
    settings = request.app.state.settings
    service = _service(request)

    try:
        user = service.authenticate(
            session,
            username=body.username,
            password=body.password,
        )
        _user_session, token = service.create_session(session, user)
        session.commit()
    except Exception:
        session.rollback()
        raise

    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )

    context = service.resolve_session(session, token)
    return _auth_user(context)


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> None:
    settings = request.app.state.settings
    service = _service(request)
    service.revoke_session(session, _cookie_token(request))
    session.commit()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.get("/auth/me", response_model=AuthUser)
def me(
    request: Request,
    session: Session = Depends(get_db_session),
) -> AuthUser:
    service = _service(request)
    context = service.resolve_session(session, _cookie_token(request))
    return _auth_user(context)
