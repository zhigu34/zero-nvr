from __future__ import annotations

import uuid

import pytest

from app.modules.cameras.talk import (
    CameraTalkConnection,
    TalkBackendHandle,
    TalkSessionError,
    TalkSessionManager,
)


class FakeTimer:
    created: list["FakeTimer"] = []

    def __init__(
        self,
        seconds,
        callback,
        args=(),
    ) -> None:
        self.seconds = seconds
        self.callback = callback
        self.args = args
        self.started = False
        self.cancelled = False
        self.daemon = False
        self.created.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback(*self.args)


class FakeBackend:
    name = "fake"
    modes = (
        "push_to_talk",
        "full_duplex",
    )

    def __init__(self) -> None:
        self.started: list[uuid.UUID] = []
        self.stopped: list[uuid.UUID] = []

    def available(self) -> bool:
        return True

    def supports(
        self,
        connection: CameraTalkConnection,
    ) -> bool:
        return True

    def start(
        self,
        *,
        talk_session_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        connection: CameraTalkConnection,
        mode: str,
    ) -> TalkBackendHandle:
        self.started.append(
            talk_session_id
        )
        return TalkBackendHandle(
            descriptor={
                "kind": "test",
                "mode": mode,
            },
            state=talk_session_id,
        )

    def stop(
        self,
        handle: TalkBackendHandle,
    ) -> None:
        assert isinstance(
            handle.state,
            uuid.UUID,
        )
        self.stopped.append(
            handle.state
        )


def connection(
    camera_id: uuid.UUID,
) -> CameraTalkConnection:
    return CameraTalkConnection(
        camera_id=camera_id,
        profile_id=uuid.uuid4(),
        profile_token="profile-main",
        audio_codec="aac",
        source_uri=(
            "rtsp://user:password@"
            "camera.local/main"
        ),
    )


def test_talk_session_is_single_talker_owner_scoped_and_revocable() -> None:
    FakeTimer.created = []
    manager = TalkSessionManager(
        timer_factory=FakeTimer
    )
    backend = FakeBackend()
    camera_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    lease = manager.start(
        camera_id=camera_id,
        owner_user_id=owner_id,
        connection=connection(
            camera_id
        ),
        backend=backend,
        mode="push_to_talk",
        ttl_seconds=30,
    )
    assert manager.active_for_camera(
        camera_id
    )
    assert backend.started == [
        lease.id
    ]

    with pytest.raises(
        TalkSessionError
    ) as busy:
        manager.start(
            camera_id=camera_id,
            owner_user_id=uuid.uuid4(),
            connection=connection(
                camera_id
            ),
            backend=backend,
            mode="push_to_talk",
            ttl_seconds=30,
        )
    assert busy.value.code == (
        "camera_talk_busy"
    )

    assert not manager.touch(
        lease.id,
        camera_id=camera_id,
        owner_user_id=uuid.uuid4(),
    )
    assert not manager.stop(
        lease.id,
        camera_id=camera_id,
        owner_user_id=uuid.uuid4(),
    )
    assert manager.active_for_camera(
        camera_id
    )

    assert manager.touch(
        lease.id,
        camera_id=camera_id,
        owner_user_id=owner_id,
        ttl_seconds=30,
    )
    assert manager.stop(
        lease.id,
        camera_id=camera_id,
        owner_user_id=owner_id,
    )
    assert not manager.active_for_camera(
        camera_id
    )
    assert backend.stopped == [
        lease.id
    ]


def test_talk_session_expiry_stops_backend() -> None:
    FakeTimer.created = []
    manager = TalkSessionManager(
        timer_factory=FakeTimer
    )
    backend = FakeBackend()
    camera_id = uuid.uuid4()
    lease = manager.start(
        camera_id=camera_id,
        owner_user_id=uuid.uuid4(),
        connection=connection(
            camera_id
        ),
        backend=backend,
        mode="full_duplex",
        ttl_seconds=15,
    )

    timer = FakeTimer.created[-1]
    assert timer.started
    timer.fire()

    assert not manager.active_for_camera(
        camera_id
    )
    assert backend.stopped == [
        lease.id
    ]
