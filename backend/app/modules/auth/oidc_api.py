from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.modules.audit.service import append_audit_event

from .oidc import (
    OidcProviderConfig,
    OidcProviderSettingsService,
)
from .oidc_identity import OidcIdentityService
from .schemas import OidcProviderPublicView
from .service import AuthService


router = APIRouter()


def _safe_next(value: str) -> str:
    candidate = value.strip()
    if (
        candidate.startswith("/")
        and not candidate.startswith("//")
    ):
        return candidate
    return "/dashboard"


def _client_info(
    request: Request,
) -> dict[str, object]:
    info: dict[str, object] = {}
    user_agent = request.headers.get(
        "user-agent"
    )
    if user_agent:
        info["user_agent"] = user_agent[:512]
    if request.client and request.client.host:
        info["source_ip"] = (
            request.client.host[:64]
        )
    return info


def _set_browser_session(
    request: Request,
    response: RedirectResponse,
    token: str,
) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=(
            settings.session_ttl_hours
            * 3600
        ),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _error_redirect(
    code: str,
) -> RedirectResponse:
    return RedirectResponse(
        url=(
            "/login?oidc_error="
            + quote(code, safe="")
        ),
        status_code=303,
    )


def _remote_client(
    request: Request,
    session: Session,
    provider: OidcProviderConfig,
):
    service = OidcProviderSettingsService(
        request.app.state.settings
    )
    client_secret = service.client_secret(
        session,
        provider,
    )

    oauth = OAuth()
    oauth.register(
        name=provider.key,
        client_id=provider.client_id,
        client_secret=client_secret,
        server_metadata_url=(
            provider.issuer
            + "/.well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": "openid profile email",
            "code_challenge_method": "S256",
        },
    )
    client = oauth.create_client(
        provider.key
    )
    if client is None:
        raise ApiError(
            status_code=500,
            code="oidc_client_unavailable",
            message=(
                "OIDC client could not "
                "be created."
            ),
        )
    return client


def _provider(
    session: Session,
    provider_key: str,
) -> OidcProviderConfig:
    provider = (
        OidcProviderSettingsService.get(
            session,
            provider_key,
        )
    )
    if not provider.enabled:
        raise ApiError(
            status_code=404,
            code="oidc_provider_not_found",
            message=(
                "OIDC provider was not found."
            ),
        )
    return provider


@router.get(
    "/auth/oidc/providers",
    response_model=list[
        OidcProviderPublicView
    ],
)
def public_oidc_providers(
    session: Session = Depends(
        get_db_session
    ),
) -> list[OidcProviderPublicView]:
    return [
        OidcProviderPublicView(
            key=item.key,
            name=item.name,
        )
        for item in (
            OidcProviderSettingsService.list(
                session
            )
        )
        if item.enabled
    ]


@router.get(
    "/auth/oidc/{provider_key}/login",
    name="oidc_login",
)
async def oidc_login(
    provider_key: str,
    request: Request,
    next_path: str = Query(
        default="/dashboard",
        alias="next",
    ),
    session: Session = Depends(
        get_db_session
    ),
):
    provider = _provider(
        session,
        provider_key,
    )
    client = _remote_client(
        request,
        session,
        provider,
    )

    request.session[
        (
            "zero_nvr_oidc_next:"
            + provider.key
        )
    ] = _safe_next(next_path)
    redirect_uri = str(
        request.url_for(
            "oidc_callback",
            provider_key=provider.key,
        )
    )
    session.commit()

    return await client.authorize_redirect(
        request,
        redirect_uri,
    )


@router.get(
    "/auth/oidc/{provider_key}/callback",
    name="oidc_callback",
)
async def oidc_callback(
    provider_key: str,
    request: Request,
    session: Session = Depends(
        get_db_session
    ),
):
    provider: OidcProviderConfig | None = None

    try:
        provider = _provider(
            session,
            provider_key,
        )
        client = _remote_client(
            request,
            session,
            provider,
        )
        oauth_token = (
            await client.authorize_access_token(
                request
            )
        )
        raw_userinfo = oauth_token.get(
            "userinfo"
        )
        if not isinstance(
            raw_userinfo,
            Mapping,
        ):
            raise ApiError(
                status_code=403,
                code="oidc_userinfo_missing",
                message=(
                    "OIDC user information "
                    "is missing."
                ),
            )

        claims: dict[str, Any] = dict(
            raw_userinfo
        )
        user = OidcIdentityService.login(
            session,
            provider=provider,
            claims=claims,
        )

        auth = AuthService(
            request.app.state.settings
        )
        _user_session, browser_token = (
            auth.create_session(
                session,
                user,
                client_info=(
                    _client_info(request)
                ),
            )
        )
        append_audit_event(
            session,
            request=request,
            actor_id=user.id,
            action="auth.oidc.login",
            resource_type="oidc_provider",
            resource_id=provider.id,
            metadata={
                "provider": provider.key,
                "issuer": provider.issuer,
            },
        )
        session.commit()

        next_key = (
            "zero_nvr_oidc_next:"
            + provider.key
        )
        next_path = _safe_next(
            str(
                request.session.pop(
                    next_key,
                    "/dashboard",
                )
            )
        )
        response = RedirectResponse(
            url=next_path,
            status_code=303,
        )
        _set_browser_session(
            request,
            response,
            browser_token,
        )
        return response

    except ApiError as exc:
        session.rollback()
        if provider is not None:
            try:
                append_audit_event(
                    session,
                    request=request,
                    actor_id=None,
                    action=(
                        "auth.oidc.login"
                    ),
                    resource_type=(
                        "oidc_provider"
                    ),
                    resource_id=provider.id,
                    result="failed",
                    reason=exc.code,
                    metadata={
                        "provider": (
                            provider.key
                        )
                    },
                )
                session.commit()
            except Exception:
                session.rollback()
        return _error_redirect(
            exc.code
        )

    except Exception:
        session.rollback()
        if provider is not None:
            try:
                append_audit_event(
                    session,
                    request=request,
                    actor_id=None,
                    action=(
                        "auth.oidc.login"
                    ),
                    resource_type=(
                        "oidc_provider"
                    ),
                    resource_id=provider.id,
                    result="failed",
                    reason=(
                        "oidc_exchange_failed"
                    ),
                    metadata={
                        "provider": (
                            provider.key
                        )
                    },
                )
                session.commit()
            except Exception:
                session.rollback()
        return _error_redirect(
            "oidc_exchange_failed"
        )
