from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.responses import StreamingResponse

from app.core.config import Settings


router = APIRouter(prefix="/zlm", tags=["media"])
_ALLOWED_APPS = {
    "zero-nvr",
    "zero-nvr-compat",
    "zero-nvr-vod",
}
_REQUEST_HEADERS = {
    "accept",
    "accept-encoding",
    "if-modified-since",
    "if-none-match",
    "if-range",
    "range",
}
_RESPONSE_HEADERS = {
    "accept-ranges",
    "cache-control",
    "content-disposition",
    "content-encoding",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "last-modified",
}


def _validated_media_path(path: str) -> str:
    normalized = path.strip("/")
    parts = normalized.split("/")
    if (
        not normalized
        or parts[0] not in _ALLOWED_APPS
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise HTTPException(status_code=404)
    return quote(normalized, safe="/._-~")


def _upstream_url(
    settings: Settings,
    *,
    path: str,
    request: Request,
) -> str:
    base = settings.zlm_base_url.rstrip("/")
    target = f"{base}/{_validated_media_path(path)}"
    raw_query = request.scope.get("query_string", b"")
    if raw_query:
        target += "?" + raw_query.decode("latin-1")
    return target


def _request_headers(request: Request) -> dict[str, str]:
    return {
        name: value
        for name, value in request.headers.items()
        if name.lower() in _REQUEST_HEADERS
    }


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower() in _RESPONSE_HEADERS
    }


async def _stream_and_close(
    client: httpx.AsyncClient,
    response: httpx.Response,
) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_raw():
            yield chunk
    finally:
        await response.aclose()
        await client.aclose()


@router.api_route(
    "/{path:path}",
    methods=["GET", "HEAD"],
)
async def proxy_zlm_media(
    path: str,
    request: Request,
) -> Response:
    settings: Settings = request.app.state.settings
    target = _upstream_url(
        settings,
        path=path,
        request=request,
    )
    timeout = httpx.Timeout(
        connect=settings.zlm_timeout_seconds,
        read=None,
        write=settings.zlm_timeout_seconds,
        pool=settings.zlm_timeout_seconds,
    )
    client = httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
    )
    try:
        upstream_request = client.build_request(
            request.method,
            target,
            headers=_request_headers(request),
        )
        upstream = await client.send(
            upstream_request,
            stream=True,
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail="ZLMediaKit media upstream is unavailable.",
        ) from exc

    headers = _response_headers(upstream)
    if request.method == "HEAD":
        await upstream.aclose()
        await client.aclose()
        return Response(
            status_code=upstream.status_code,
            headers=headers,
        )

    return StreamingResponse(
        _stream_and_close(client, upstream),
        status_code=upstream.status_code,
        headers=headers,
    )
