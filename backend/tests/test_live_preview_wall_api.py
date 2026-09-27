from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.integrations.zlm import ZlmMediaProbe, ZlmTrackProbe
from app.modules.auth.models import User
from app.modules.cameras.media_runtime import CameraMediaRuntimeService
from app.modules.cameras.models import CameraStreamBinding
from tests.test_camera_live_api import ADMIN_PASSWORD, make_app


SOCKET_PATH = "/api/v1/live/previews/ws"
ORIGIN_HEADERS = {"origin": "http://testserver"}


def setup_administrator(client: TestClient) -> None:
    assert client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": ADMIN_PASSWORD,
        },
    ).status_code == 201


def install_live_source_fakes(monkeypatch) -> list[str]:
    opened: list[str] = []

    def fake_ensure(self, desired, *, wait_online_seconds=None):
        return [item.reference for item in desired]

    class FakeZlmAdapter:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def media_probe(self, *, app: str, stream: str, schema: str):
            return ZlmMediaProbe(
                stream=stream,
                video=ZlmTrackProbe(
                    kind="video",
                    codec="h265",
                    ready=True,
                    width=1920,
                    height=1080,
                    fps=15.0,
                ),
                audio=None,
            )

    async def fail_if_opened(
        _settings,
        *,
        source_url: str,
        width: int,
        fps: int,
    ):
        opened.append(source_url)
        raise AssertionError(
            f"unauthorized preview opened at {width}x{fps}"
        )

    monkeypatch.setattr(
        CameraMediaRuntimeService,
        "ensure_streams",
        fake_ensure,
    )
    monkeypatch.setattr(
        "app.modules.cameras.api.ZlmAdapter",
        FakeZlmAdapter,
    )
    monkeypatch.setattr(
        "app.modules.cameras.live_preview_wall_api.open_live_preview",
        fail_if_opened,
        raising=False,
    )
    return opened


def create_camera_and_descriptor(
    client: TestClient,
    *,
    name: str,
    host: str,
) -> tuple[str, str]:
    created = client.post(
        "/api/v1/cameras",
        json={
            "mode": "manual_rtsp",
            "name": name,
            "location": "Office",
            "primary_stream": {
                "name": "Main",
                "rtsp_url": (
                    f"rtsp://alice:camera-secret@{host}/main"
                    "?token=camera-token"
                ),
            },
            "secondary_stream": None,
        },
    )
    assert created.status_code == 201
    camera_id = created.json()["id"]
    descriptor = client.get(
        f"/api/v1/cameras/{camera_id}/live?quality=low"
    )
    assert descriptor.status_code == 200
    return camera_id, descriptor.json()["media_session_id"]


def sync_message(
    *,
    camera_id: str,
    media_session_id: str,
    subscription_id: int = 1,
) -> str:
    return json.dumps(
        {
            "type": "sync",
            "version": 1,
            "layout_slots": 9,
            "streams": [
                {
                    "slot": 0,
                    "subscription_id": subscription_id,
                    "camera_id": camera_id,
                    "media_session_id": media_session_id,
                }
            ],
        }
    )


def receive_json_with_timeout(websocket, timeout: float = 1.0):
    result: dict[str, object] = {}

    def receive() -> None:
        try:
            result["message"] = websocket.receive_json()
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        websocket.close()
        thread.join(1)
        raise AssertionError("preview wall did not produce a message")
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result["message"]


def receive_slot_error(websocket) -> dict[str, object]:
    for _ in range(3):
        message = receive_json_with_timeout(websocket)
        assert isinstance(message, dict)
        if message.get("type") == "error":
            return message
    raise AssertionError("preview wall did not produce a slot error")


def receive_message_with_timeout(websocket, timeout: float = 1.0):
    result: dict[str, object] = {}

    def receive() -> None:
        try:
            result["message"] = websocket.receive()
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        websocket.close()
        thread.join(1)
        raise AssertionError("preview wall did not produce a frame")
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result["message"]


class ControlledPreview:
    def __init__(self) -> None:
        import asyncio

        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.closed = threading.Event()
        self.close_count = 0

    def push(self, frame: bytes) -> None:
        self.loop.call_soon_threadsafe(self.queue.put_nowait, frame)

    async def frames(self):
        while True:
            frame = await self.queue.get()
            if frame is None:
                return
            yield frame

    async def close(self) -> None:
        self.close_count += 1
        self.closed.set()
        self.queue.put_nowait(None)


def wait_for_previews(
    previews: dict[str, ControlledPreview],
    count: int,
) -> None:
    deadline = time.monotonic() + 1
    while len(previews) < count and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(previews) == count


def login_administrator(client: TestClient) -> None:
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    ).status_code == 200


def assert_socket_rejected(
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            SOCKET_PATH,
            headers=headers or {},
        ):
            pass


def test_preview_wall_socket_requires_same_origin_interactive_session(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_administrator(client)
        assert_socket_rejected(client, headers=ORIGIN_HEADERS)

        login_administrator(client)
        assert_socket_rejected(client)
        assert_socket_rejected(
            client,
            headers={"origin": "https://attacker.example"},
        )

        created_token = client.post(
            "/api/v1/api-tokens",
            json={
                "name": "Preview test",
                "permissions": ["camera.view"],
            },
        )
        assert created_token.status_code == 201
        token = created_token.json()["token"]
        client.cookies.clear()
        assert_socket_rejected(
            client,
            headers={
                **ORIGIN_HEADERS,
                "authorization": f"Bearer {token}",
            },
        )


def test_preview_wall_socket_requires_camera_view_permission(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_administrator(client)
        login_administrator(client)
        role = client.post(
            "/api/v1/roles",
            json={
                "name": "No Cameras",
                "permissions": ["system.view"],
            },
        )
        assert role.status_code == 201
        user = client.post(
            "/api/v1/users",
            json={
                "username": "nocamera",
                "display_name": "No Camera User",
                "password": "no-camera-correct-horse-battery",
                "role_ids": [role.json()["id"]],
            },
        )
        assert user.status_code == 201
        assert client.post("/api/v1/auth/logout").status_code == 204
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "nocamera",
                "password": "no-camera-correct-horse-battery",
            },
        ).status_code == 200

        assert_socket_rejected(client, headers=ORIGIN_HEADERS)


def test_preview_wall_socket_accepts_same_origin_administrator(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_administrator(client)
        login_administrator(client)

        with client.websocket_connect(
            SOCKET_PATH,
            headers=ORIGIN_HEADERS,
        ) as websocket:
            websocket.close()


def test_preview_wall_rejects_camera_scope_and_cross_user_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    opened = install_live_source_fakes(monkeypatch)

    with TestClient(app) as client:
        setup = client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": ADMIN_PASSWORD,
            },
        )
        admin_id = setup.json()["id"]
        login_administrator(client)
        camera_id, media_session_id = create_camera_and_descriptor(
            client,
            name="Scoped Camera",
            host="10.0.0.10",
        )

        scoped_none = client.put(
            f"/api/v1/users/{admin_id}/camera-scope",
            json={"mode": "none"},
        )
        assert scoped_none.status_code == 200
        with client.websocket_connect(
            SOCKET_PATH, headers=ORIGIN_HEADERS
        ) as websocket:
            websocket.send_text(
                sync_message(
                    camera_id=camera_id,
                    media_session_id=media_session_id,
                )
            )
            denied = receive_slot_error(websocket)
            assert denied["code"] == "camera_not_found"

        assert client.put(
            f"/api/v1/users/{admin_id}/camera-scope",
            json={"mode": "inherit"},
        ).status_code == 200
        role = client.post(
            "/api/v1/roles",
            json={
                "name": "Wall Viewer",
                "permissions": ["camera.view"],
            },
        )
        assert role.status_code == 201
        assert client.put(
            f"/api/v1/roles/{role.json()['id']}/camera-scope",
            json={"mode": "all"},
        ).status_code == 200
        assert client.post(
            "/api/v1/users",
            json={
                "username": "wallviewer",
                "display_name": "Wall Viewer",
                "password": "wall-viewer-correct-horse-battery",
                "role_ids": [role.json()["id"]],
            },
        ).status_code == 201
        assert client.post("/api/v1/auth/logout").status_code == 204
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "wallviewer",
                "password": "wall-viewer-correct-horse-battery",
            },
        ).status_code == 200

        with client.websocket_connect(
            SOCKET_PATH, headers=ORIGIN_HEADERS
        ) as websocket:
            websocket.send_text(
                sync_message(
                    camera_id=camera_id,
                    media_session_id=media_session_id,
                    subscription_id=2,
                )
            )
            denied = receive_slot_error(websocket)
            assert denied["code"] == "media_session_not_found"

    assert opened == []


def test_preview_wall_rechecks_permission_for_new_subscriptions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    opened = install_live_source_fakes(monkeypatch)

    with TestClient(app) as client:
        setup_administrator(client)
        login_administrator(client)
        camera_id, media_session_id = create_camera_and_descriptor(
            client,
            name="Permission Refresh Camera",
            host="10.0.0.15",
        )

        with client.websocket_connect(
            SOCKET_PATH, headers=ORIGIN_HEADERS
        ) as websocket:
            with app.state.database.session() as session:
                admin = session.scalar(
                    select(User).where(User.username == "admin")
                )
                assert admin is not None
                admin.roles = []
                session.commit()

            websocket.send_text(
                sync_message(
                    camera_id=camera_id,
                    media_session_id=media_session_id,
                )
            )
            denied = receive_slot_error(websocket)
            assert denied["code"] == "permission_denied"

    assert opened == []


def test_preview_wall_rejects_cross_camera_expired_and_changed_sessions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    opened = install_live_source_fakes(monkeypatch)

    with TestClient(app) as client:
        setup_administrator(client)
        login_administrator(client)
        first_camera, first_session = create_camera_and_descriptor(
            client,
            name="First Camera",
            host="10.0.0.11",
        )
        second_camera, _ = create_camera_and_descriptor(
            client,
            name="Second Camera",
            host="10.0.0.12",
        )

        with client.websocket_connect(
            SOCKET_PATH, headers=ORIGIN_HEADERS
        ) as websocket:
            websocket.send_text(
                sync_message(
                    camera_id=second_camera,
                    media_session_id=first_session,
                )
            )
            assert receive_slot_error(websocket)["code"] == (
                "media_session_not_found"
            )

        expired_camera, expired_session = create_camera_and_descriptor(
            client,
            name="Expired Camera",
            host="10.0.0.13",
        )
        assert app.state.media_sessions.revoke(uuid.UUID(expired_session))
        with client.websocket_connect(
            SOCKET_PATH, headers=ORIGIN_HEADERS
        ) as websocket:
            websocket.send_text(
                sync_message(
                    camera_id=expired_camera,
                    media_session_id=expired_session,
                    subscription_id=2,
                )
            )
            assert receive_slot_error(websocket)["code"] == (
                "media_session_not_found"
            )

        changed_camera, changed_session = create_camera_and_descriptor(
            client,
            name="Changed Camera",
            host="10.0.0.14",
        )
        with app.state.database.session() as session:
            admin = session.scalar(
                select(User).where(User.username == "admin")
            )
            assert admin is not None
            stream_context = app.state.media_sessions.stream_context(
                uuid.UUID(changed_session),
                owner_user_id=admin.id,
                camera_id=uuid.UUID(changed_camera),
            )
            assert stream_context is not None
            _profile_id, purpose = stream_context
            binding = session.scalar(
                select(CameraStreamBinding).where(
                    CameraStreamBinding.camera_id
                    == uuid.UUID(changed_camera),
                    CameraStreamBinding.purpose == purpose,
                )
            )
            assert binding is not None
            session.delete(binding)
            session.commit()
        with client.websocket_connect(
            SOCKET_PATH, headers=ORIGIN_HEADERS
        ) as websocket:
            websocket.send_text(
                sync_message(
                    camera_id=changed_camera,
                    media_session_id=changed_session,
                    subscription_id=3,
                )
            )
            assert receive_slot_error(websocket)["code"] == (
                "media_session_stream_changed"
            )

    assert opened == []


def test_preview_wall_malformed_sync_is_fatal(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_administrator(client)
        login_administrator(client)
        with client.websocket_connect(
            SOCKET_PATH, headers=ORIGIN_HEADERS
        ) as websocket:
            websocket.send_text("not-json")
            fatal = websocket.receive_json()
            assert fatal["type"] == "fatal"
            assert fatal["code"] == "invalid_sync"
            with pytest.raises(WebSocketDisconnect) as caught:
                websocket.receive_json()
            assert caught.value.code == 1008


def test_preview_wall_revocation_isolated_and_disconnect_cleans_all(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    install_live_source_fakes(monkeypatch)
    previews: dict[str, ControlledPreview] = {}

    async def open_preview(
        _settings,
        *,
        source_url: str,
        width: int,
        fps: int,
    ):
        assert (width, fps) == (480, 3)
        session_id = parse_qs(urlsplit(source_url).query)["zn_sid"][0]
        preview = ControlledPreview()
        previews[session_id] = preview
        return preview

    monkeypatch.setattr(
        "app.modules.cameras.live_preview_wall_api.open_live_preview",
        open_preview,
    )

    with TestClient(app) as client:
        setup_administrator(client)
        login_administrator(client)
        first_camera, first_session = create_camera_and_descriptor(
            client,
            name="Wall Camera One",
            host="10.0.0.21",
        )
        second_camera, second_session = create_camera_and_descriptor(
            client,
            name="Wall Camera Two",
            host="10.0.0.22",
        )
        payload = {
            "type": "sync",
            "version": 1,
            "layout_slots": 9,
            "streams": [
                {
                    "slot": 0,
                    "subscription_id": 101,
                    "camera_id": first_camera,
                    "media_session_id": first_session,
                },
                {
                    "slot": 1,
                    "subscription_id": 102,
                    "camera_id": second_camera,
                    "media_session_id": second_session,
                },
            ],
        }

        with client.websocket_connect(
            SOCKET_PATH, headers=ORIGIN_HEADERS
        ) as websocket:
            websocket.send_json(payload)
            wait_for_previews(previews, 2)
            previews[first_session].push(b"\xff\xd8first\xff\xd9")
            previews[second_session].push(b"\xff\xd8second\xff\xd9")

            initial_slots: set[int] = set()
            while initial_slots != {0, 1}:
                message = receive_message_with_timeout(websocket)
                if message.get("bytes") is not None:
                    initial_slots.add(message["bytes"][1])

            assert app.state.media_sessions.revoke(
                uuid.UUID(first_session)
            )
            assert previews[first_session].closed.wait(1)
            previews[second_session].push(
                b"\xff\xd8still-working\xff\xd9"
            )

            saw_error = False
            saw_second_frame = False
            for _ in range(4):
                message = receive_message_with_timeout(websocket)
                if message.get("text") is not None:
                    body = json.loads(message["text"])
                    if body.get("type") == "error":
                        assert body["slot"] == 0
                        assert body["subscription_id"] == 101
                        saw_error = True
                if message.get("bytes") is not None:
                    if message["bytes"][1] == 1:
                        saw_second_frame = True
                if saw_error and saw_second_frame:
                    break
            assert saw_error
            assert saw_second_frame
            websocket.close()

        assert previews[second_session].closed.wait(1)
        assert previews[first_session].close_count == 1
        assert previews[second_session].close_count == 1
        registry_state = app.state.media_sessions._sessions[
            uuid.UUID(second_session)
        ]
        assert registry_state.cleanups == {}
