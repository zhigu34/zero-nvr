from __future__ import annotations

import uuid

from app.modules.cameras.media_sessions import (
    MediaSessionRegistry,
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


def test_media_session_is_owner_camera_scoped_and_revocable() -> None:
    FakeTimer.created = []
    registry = MediaSessionRegistry(
        timer_factory=FakeTimer
    )
    user_id = uuid.uuid4()
    camera_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    session_id = registry.issue(
        owner_user_id=user_id,
        camera_id=camera_id,
        ttl_seconds=30,
        profile_id=profile_id,
        purpose="LIVE_HIGH",
    )

    assert registry.active(session_id)
    assert registry.stream_context(
        session_id,
        owner_user_id=user_id,
        camera_id=camera_id,
    ) == (profile_id, "LIVE_HIGH")
    assert registry.authorize(
        session_id,
        owner_user_id=user_id,
        camera_id=camera_id,
    )
    assert not registry.authorize(
        session_id,
        owner_user_id=uuid.uuid4(),
        camera_id=camera_id,
    )
    assert not registry.revoke(
        session_id,
        owner_user_id=uuid.uuid4(),
        camera_id=camera_id,
    )
    assert registry.active(session_id)

    cleaned: list[str] = []
    assert registry.register_cleanup(
        session_id,
        key="transport:test",
        cleanup=lambda: cleaned.append("done"),
    )
    assert registry.revoke(
        session_id,
        owner_user_id=user_id,
        camera_id=camera_id,
    )
    assert not registry.active(session_id)
    assert cleaned == ["done"]


def test_media_session_renewal_replaces_expiry_without_cleanup() -> None:
    FakeTimer.created = []
    registry = MediaSessionRegistry(
        timer_factory=FakeTimer
    )
    user_id = uuid.uuid4()
    camera_id = uuid.uuid4()
    cleaned: list[str] = []
    session_id = registry.issue(
        owner_user_id=user_id,
        camera_id=camera_id,
        ttl_seconds=15,
    )
    assert registry.register_cleanup(
        session_id,
        key="transport:test",
        cleanup=lambda: cleaned.append("expired"),
    )

    original = FakeTimer.created[-1]
    assert registry.renew(
        session_id,
        owner_user_id=user_id,
        camera_id=camera_id,
        ttl_seconds=30,
    )
    renewed = FakeTimer.created[-1]

    assert original.cancelled
    assert renewed is not original
    assert renewed.seconds == 30
    assert renewed.started
    assert registry.active(session_id)
    assert cleaned == []

    # A stale expiry callback must not revoke the renewed session even if it
    # races with timer cancellation.
    original.callback(*original.args)
    assert registry.active(session_id)
    assert cleaned == []

    renewed.fire()
    assert not registry.active(session_id)
    assert cleaned == ["expired"]


def test_media_session_expiry_runs_registered_cleanup() -> None:
    FakeTimer.created = []
    registry = MediaSessionRegistry(
        timer_factory=FakeTimer
    )
    cleaned: list[str] = []
    session_id = registry.issue(
        owner_user_id=uuid.uuid4(),
        camera_id=uuid.uuid4(),
        ttl_seconds=15,
    )
    assert registry.register_cleanup(
        session_id,
        key="transport:test",
        cleanup=lambda: cleaned.append("expired"),
    )

    timer = FakeTimer.created[-1]
    assert timer.started
    timer.fire()

    assert not registry.active(session_id)
    assert cleaned == ["expired"]
