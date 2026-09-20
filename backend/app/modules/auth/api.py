from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.modules.audit.service import append_audit_event
from app.modules.notifications.models import NotificationDelivery

from .dependencies import get_auth_context
from .schemas import (
    AuthUser,
    InitialAdministratorCreate,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetCompleteRequest,
    PasswordResetCompleteView,
    PasswordResetRequest,
    PasswordResetRequestAccepted,
    SessionSummary,
    SetupStatus,
)
from .password_reset import PasswordResetService
from .service import AuthContext, AuthService


router = APIRouter()


def _service(request: Request) -> AuthService:
    return AuthService(request.app.state.settings)


def _cookie_token(request: Request) -> str | None:
    settings = request.app.state.settings
    return request.cookies.get(settings.session_cookie_name)


def _client_info(request: Request) -> dict[str, object]:
    info: dict[str, object] = {}
    user_agent = request.headers.get("user-agent")
    if user_agent:
        info["user_agent"] = user_agent[:512]
    if request.client and request.client.host:
        info["source_ip"] = request.client.host[:64]
    return info


def _set_session_cookie(
    *,
    request: Request,
    response: Response,
    token: str,
) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(
    *,
    request: Request,
    response: Response,
) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


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
    service = _service(request)

    try:
        user = service.authenticate(
            session,
            username=body.username,
            password=body.password,
        )
        _user_session, token = service.create_session(
            session,
            user,
            client_info=_client_info(request),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    _set_session_cookie(
        request=request,
        response=response,
        token=token,
    )

    context = service.resolve_session(session, token)
    return _auth_user(context)


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> None:
    service = _service(request)
    service.revoke_session(session, _cookie_token(request))
    session.commit()
    _clear_session_cookie(
        request=request,
        response=response,
    )


@router.get("/auth/me", response_model=AuthUser)
def me(
    context: AuthContext = Depends(get_auth_context),
) -> AuthUser:
    return _auth_user(context)





@router.post(
    "/auth/password-reset/request",
    response_model=PasswordResetRequestAccepted,
    status_code=202,
)
def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> PasswordResetRequestAccepted:
    service = PasswordResetService(
        request.app.state.settings
    )
    issue = None
    try:
        issue = service.issue(
            session,
            identifier=body.identifier,
            request_metadata=_client_info(request),
        )
        if issue is not None:
            append_audit_event(
                session,
                request=request,
                actor_id=None,
                action="auth.password_reset.request",
                resource_type="user",
                resource_id=issue.user_id,
                metadata={
                    "delivery_id": str(issue.delivery_id),
                },
            )
        session.commit()
    except Exception:
        # Public request remains non-enumerating. Configuration or
        # persistence failures must not reveal whether the account exists.
        session.rollback()
        return PasswordResetRequestAccepted()

    if issue is not None:
        try:
            request.app.state.notification_tasks.deliver(
                issue.delivery_id
            )
        except Exception:
            delivery = session.get(
                NotificationDelivery,
                issue.delivery_id,
            )
            if delivery is not None:
                delivery.state = "FAILED"
                delivery.last_error_code = (
                    "notification_queue_unavailable"
                )
                session.commit()

    return PasswordResetRequestAccepted()


@router.post(
    "/auth/password-reset/complete",
    response_model=PasswordResetCompleteView,
)
def complete_password_reset(
    body: PasswordResetCompleteRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> PasswordResetCompleteView:
    service = PasswordResetService(
        request.app.state.settings
    )
    try:
        user = service.consume(
            session,
            token=body.token,
            new_password=body.new_password,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=user.id,
            action="auth.password_reset.complete",
            resource_type="user",
            resource_id=user.id,
            metadata={
                "sessions_revoked": True,
                "reset_token_single_use": True,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return PasswordResetCompleteView()


@router.post("/auth/password/change", response_model=AuthUser)
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_db_session),
) -> AuthUser:
    service = _service(request)
    try:
        _new_session, token = service.change_password(
            session,
            context=context,
            current_password=body.current_password,
            new_password=body.new_password,
            client_info=_client_info(request),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    _set_session_cookie(
        request=request,
        response=response,
        token=token,
    )
    refreshed = service.resolve_session(session, token)
    return _auth_user(refreshed)


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(
    context: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_db_session),
) -> list[SessionSummary]:
    items = AuthService.list_active_sessions(
        session,
        user_id=context.user.id,
    )
    return [
        SessionSummary(
            id=item.id,
            created_at=item.created_at,
            last_seen_at=item.last_seen_at,
            expires_at=item.expires_at,
            current=item.id == context.session.id,
            client_info=item.client_info,
        )
        for item in items
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_db_session),
) -> None:
    target = AuthService.revoke_owned_session(
        session,
        user_id=context.user.id,
        session_id=session_id,
    )
    session.commit()

    if target.id == context.session.id:
        _clear_session_cookie(
            request=request,
            response=response,
        )
