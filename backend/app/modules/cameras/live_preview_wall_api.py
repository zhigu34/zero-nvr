from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.core.errors import ApiError
from app.integrations.zlm import ZlmMediaAccess
from app.modules.auth.camera_scope import CameraScopeService
from app.modules.auth.dependencies import resolve_auth_context

from .api import live_selection_for_media_session
from .live_preview import open_live_preview
from .live_preview_wall import (
    OpenedPreview,
    PreviewWallProtocolError,
    PreviewWallSession,
    PreviewWallSubscription,
    parse_preview_wall_sync,
)


router = APIRouter()


def _effective_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def same_origin_websocket(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return False
    parsed = urlsplit(origin)
    expected_scheme = (
        "https" if websocket.url.scheme == "wss" else "http"
    )
    if (
        parsed.scheme.lower() != expected_scheme
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return False
    try:
        origin_port = parsed.port
    except ValueError:
        return False
    return (
        parsed.hostname is not None
        and websocket.url.hostname is not None
        and parsed.hostname.lower() == websocket.url.hostname.lower()
        and _effective_port(parsed.scheme.lower(), origin_port)
        == _effective_port(expected_scheme, websocket.url.port)
    )


async def _reject(websocket: WebSocket) -> None:
    await websocket.close(code=1008)


@router.websocket("/live/previews/ws")
async def preview_wall_socket(websocket: WebSocket) -> None:
    if not same_origin_websocket(websocket):
        await _reject(websocket)
        return
    try:
        with websocket.app.state.database.session() as session:
            context = resolve_auth_context(websocket, session)
            if context.session is None:
                await _reject(websocket)
                return
            if "camera.view" not in context.permissions:
                await _reject(websocket)
                return
            user_id = context.user.id
    except ApiError:
        await _reject(websocket)
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()
    media_sessions = websocket.app.state.media_sessions
    settings = websocket.app.state.settings
    wall: PreviewWallSession

    async def open_source(
        subscription: PreviewWallSubscription,
        profile,
    ) -> OpenedPreview:
        with websocket.app.state.database.session() as session:
            current_context = resolve_auth_context(websocket, session)
            if (
                current_context.session is None
                or current_context.user.id != user_id
                or "camera.view" not in current_context.permissions
            ):
                raise ApiError(
                    status_code=403,
                    code="permission_denied",
                    message=(
                        "You do not have permission to view cameras."
                    ),
                )
            current_role_ids = [
                role.id for role in current_context.user.roles
            ]
            scope = CameraScopeService.effective_scope(
                session,
                user_id=user_id,
                role_ids=current_role_ids,
            )
            if not scope.allows(subscription.camera_id):
                raise ApiError(
                    status_code=404,
                    code="camera_not_found",
                    message="Camera was not found.",
                )
            selection = live_selection_for_media_session(
                websocket,
                media_session_id=(
                    subscription.media_session_id
                ),
                camera_id=subscription.camera_id,
                user_id=user_id,
                session=session,
            )
            session.commit()

        source_url, _expires_at = ZlmMediaAccess(settings).sign_url(
            selection.runtime.internal_rtsp_url(
                selection.reference
            ),
            app=selection.reference.app,
            stream=selection.reference.stream,
            ttl_seconds=ZlmMediaAccess.live_ttl_seconds,
            session_id=subscription.media_session_id,
        )
        preview = await open_live_preview(
            settings,
            source_url=source_url,
            width=profile.width,
            fps=profile.fps,
        )
        cleanup_key = f"preview-wall:{uuid.uuid4()}"

        def revoked() -> None:
            def schedule() -> None:
                asyncio.create_task(
                    wall.fail_subscription(
                        subscription,
                        code="media_session_not_found",
                        message=(
                            "Live media session was revoked or expired."
                        ),
                    )
                )

            with suppress(RuntimeError):
                loop.call_soon_threadsafe(schedule)

        if not media_sessions.register_cleanup(
            subscription.media_session_id,
            key=cleanup_key,
            cleanup=revoked,
        ):
            await preview.close()
            raise ApiError(
                status_code=404,
                code="media_session_not_found",
                message=(
                    "Live media session was not found or has expired."
                ),
            )

        def release() -> None:
            media_sessions.unregister_cleanup(
                subscription.media_session_id,
                key=cleanup_key,
            )

        return OpenedPreview(preview=preview, release=release)

    wall = PreviewWallSession(open_source)

    async def send_messages() -> None:
        while True:
            message = await wall.next_message()
            if isinstance(message, bytes):
                await websocket.send_bytes(message)
            else:
                await websocket.send_text(message)

    async def receive_syncs() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            raw = message.get("text")
            if raw is None:
                error = PreviewWallProtocolError(
                    "invalid_sync",
                    "Preview wall sync must be a text message.",
                )
            else:
                try:
                    sync = parse_preview_wall_sync(raw)
                except PreviewWallProtocolError as exc:
                    error = exc
                else:
                    await wall.apply_sync(sync)
                    continue
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "fatal",
                        "code": error.code,
                        "message": str(error),
                    },
                    separators=(",", ":"),
                )
            )
            await websocket.close(code=1008)
            return

    sender = asyncio.create_task(send_messages())
    receiver = asyncio.create_task(receive_syncs())
    try:
        done, _pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            with suppress(WebSocketDisconnect, RuntimeError):
                task.result()
    finally:
        sender.cancel()
        receiver.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await sender
        with suppress(asyncio.CancelledError, Exception):
            await receiver
        await wall.close()
