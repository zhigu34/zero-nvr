from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.modules.cameras.live_preview import LivePreviewError
from app.modules.cameras.live_preview_wall import (
    OpenedPreview,
    PreviewWallProtocolError,
    PreviewWallSession,
    PreviewWallSubscription,
    PreviewWallSync,
    encode_preview_wall_frame,
    parse_preview_wall_sync,
    preview_wall_profile,
)


CAMERA_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
MEDIA_SESSION_ID = uuid.UUID(
    "00000000-0000-0000-0000-000000000002"
)


def sync_payload(**updates: object) -> str:
    payload: dict[str, object] = {
        "type": "sync",
        "version": 1,
        "layout_slots": 9,
        "streams": [
            {
                "slot": 0,
                "subscription_id": 42,
                "camera_id": str(CAMERA_ID),
                "media_session_id": str(MEDIA_SESSION_ID),
            }
        ],
    }
    payload.update(updates)
    return json.dumps(payload)


def test_preview_wall_profiles_are_fixed_by_layout() -> None:
    assert preview_wall_profile(4).width == 640
    assert preview_wall_profile(4).fps == 5
    assert preview_wall_profile(9).width == 480
    assert preview_wall_profile(9).fps == 3
    assert preview_wall_profile(16).width == 320
    assert preview_wall_profile(16).fps == 2

    with pytest.raises(PreviewWallProtocolError):
        preview_wall_profile(1)


def test_parse_preview_wall_sync_returns_immutable_values() -> None:
    parsed = parse_preview_wall_sync(sync_payload())

    assert parsed.layout_slots == 9
    assert parsed.streams == (
        PreviewWallSubscription(
            slot=0,
            subscription_id=42,
            camera_id=CAMERA_ID,
            media_session_id=MEDIA_SESSION_ID,
        ),
    )
    with pytest.raises(AttributeError):
        parsed.layout_slots = 4  # type: ignore[misc]


@pytest.mark.parametrize(
    "raw",
    [
        "x" * (64 * 1024 + 1),
        "not-json",
        sync_payload(version=2),
        sync_payload(type="other"),
        sync_payload(layout_slots=1),
        sync_payload(streams=[{"slot": 0}]),
        sync_payload(
            streams=[
                {
                    "slot": 0,
                    "subscription_id": 1,
                    "camera_id": "not-a-uuid",
                    "media_session_id": str(MEDIA_SESSION_ID),
                }
            ]
        ),
        sync_payload(
            streams=[
                {
                    "slot": 0,
                    "subscription_id": 1,
                    "camera_id": str(CAMERA_ID),
                    "media_session_id": str(MEDIA_SESSION_ID),
                },
                {
                    "slot": 0,
                    "subscription_id": 2,
                    "camera_id": str(CAMERA_ID),
                    "media_session_id": str(MEDIA_SESSION_ID),
                },
            ]
        ),
        sync_payload(
            streams=[
                {
                    "slot": 9,
                    "subscription_id": 1,
                    "camera_id": str(CAMERA_ID),
                    "media_session_id": str(MEDIA_SESSION_ID),
                }
            ]
        ),
        sync_payload(
            streams=[
                {
                    "slot": slot,
                    "subscription_id": slot,
                    "camera_id": str(CAMERA_ID),
                    "media_session_id": str(MEDIA_SESSION_ID),
                }
                for slot in range(17)
            ],
            layout_slots=16,
        ),
        sync_payload(
            streams=[
                {
                    "slot": 0,
                    "subscription_id": -1,
                    "camera_id": str(CAMERA_ID),
                    "media_session_id": str(MEDIA_SESSION_ID),
                }
            ]
        ),
        sync_payload(
            streams=[
                {
                    "slot": 0,
                    "subscription_id": 2**32,
                    "camera_id": str(CAMERA_ID),
                    "media_session_id": str(MEDIA_SESSION_ID),
                }
            ]
        ),
    ],
)
def test_parse_preview_wall_sync_rejects_invalid_messages(raw: str) -> None:
    with pytest.raises(PreviewWallProtocolError):
        parse_preview_wall_sync(raw)


def test_encode_preview_wall_frame_uses_six_byte_header() -> None:
    subscription = PreviewWallSubscription(
        slot=3,
        subscription_id=0x12345678,
        camera_id=CAMERA_ID,
        media_session_id=MEDIA_SESSION_ID,
    )

    encoded = encode_preview_wall_frame(
        subscription,
        b"\xff\xd8jpeg\xff\xd9",
    )

    assert encoded == (
        b"\x01\x03\x12\x34\x56\x78\xff\xd8jpeg\xff\xd9"
    )

    with pytest.raises(LivePreviewError):
        encode_preview_wall_frame(subscription, b"not-jpeg")
    with pytest.raises(LivePreviewError):
        encode_preview_wall_frame(
            subscription,
            b"\xff\xd8" + b"x" * (2 * 1024 * 1024) + b"\xff\xd9",
        )


class FakePreview:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes | Exception | None] = (
            asyncio.Queue()
        )
        self.closed = 0

    async def frames(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def close(self) -> None:
        self.closed += 1
        await self.queue.put(None)


def subscription(
    slot: int,
    subscription_id: int,
) -> PreviewWallSubscription:
    return PreviewWallSubscription(
        slot=slot,
        subscription_id=subscription_id,
        camera_id=uuid.UUID(int=slot + 1),
        media_session_id=uuid.UUID(int=subscription_id + 1),
    )


async def wait_until(predicate) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


@pytest.mark.asyncio
async def test_preview_wall_session_reuses_changes_and_removes_sources() -> None:
    opened: dict[int, FakePreview] = {}
    released: list[int] = []

    async def open_source(item, profile):
        assert profile.width == 480
        preview = FakePreview()
        opened[item.subscription_id] = preview
        return OpenedPreview(
            preview=preview,
            release=lambda: released.append(item.subscription_id),
        )

    wall = PreviewWallSession(open_source)
    first = subscription(0, 10)
    await wall.apply_sync(PreviewWallSync(9, (first,)))
    await wait_until(lambda: 10 in opened)

    await wall.apply_sync(PreviewWallSync(9, (first,)))
    await asyncio.sleep(0)
    assert list(opened) == [10]

    replacement = subscription(0, 11)
    await wall.apply_sync(PreviewWallSync(9, (replacement,)))
    await wait_until(lambda: 11 in opened)
    assert opened[10].closed == 1
    assert released.count(10) == 1

    await wall.apply_sync(PreviewWallSync(9, ()))
    assert opened[11].closed == 1
    assert released.count(11) == 1
    await wall.close()


@pytest.mark.asyncio
async def test_preview_wall_session_restarts_source_when_profile_changes() -> None:
    opened: list[tuple[FakePreview, int]] = []

    async def open_source(_item, profile):
        preview = FakePreview()
        opened.append((preview, profile.width))
        return OpenedPreview(preview=preview, release=lambda: None)

    wall = PreviewWallSession(open_source)
    item = subscription(0, 12)
    await wall.apply_sync(PreviewWallSync(9, (item,)))
    await wait_until(lambda: len(opened) == 1)

    await wall.apply_sync(PreviewWallSync(4, (item,)))
    await wait_until(lambda: len(opened) == 2)

    assert [width for _preview, width in opened] == [480, 640]
    assert opened[0][0].closed == 1
    await wall.close()


@pytest.mark.asyncio
async def test_preview_wall_session_keeps_latest_frame_and_drains_fairly() -> None:
    opened: dict[int, FakePreview] = {}

    async def open_source(item, _profile):
        preview = FakePreview()
        opened[item.slot] = preview
        return OpenedPreview(preview=preview, release=lambda: None)

    wall = PreviewWallSession(open_source)
    zero = subscription(0, 20)
    one = subscription(1, 21)
    await wall.apply_sync(PreviewWallSync(9, (zero, one)))
    await wait_until(lambda: len(opened) == 2)

    await opened[0].queue.put(b"\xff\xd8old\xff\xd9")
    await opened[0].queue.put(b"\xff\xd8latest\xff\xd9")
    await opened[1].queue.put(b"\xff\xd8other\xff\xd9")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    binaries: list[bytes] = []
    while len(binaries) < 2:
        message = await asyncio.wait_for(wall.next_message(), 1)
        if isinstance(message, bytes):
            binaries.append(message)

    assert binaries[0] == encode_preview_wall_frame(
        zero, b"\xff\xd8latest\xff\xd9"
    )
    assert binaries[1] == encode_preview_wall_frame(
        one, b"\xff\xd8other\xff\xd9"
    )
    await wall.close()


@pytest.mark.asyncio
async def test_preview_wall_session_coalesces_syncs_without_starving_frames() -> None:
    opened: dict[int, FakePreview] = {}

    async def open_source(item, _profile):
        preview = FakePreview()
        opened[item.slot] = preview
        return OpenedPreview(preview=preview, release=lambda: None)

    wall = PreviewWallSession(open_source)
    item = subscription(0, 22)
    sync = PreviewWallSync(9, (item,))
    for _ in range(100):
        await wall.apply_sync(sync)
    await wait_until(lambda: 0 in opened)
    await opened[0].queue.put(b"\xff\xd8working\xff\xd9")
    await asyncio.sleep(0)

    first = await asyncio.wait_for(wall.next_message(), 1)
    second = await asyncio.wait_for(wall.next_message(), 1)
    assert isinstance(first, str)
    assert json.loads(first)["type"] == "synced"
    assert second == encode_preview_wall_frame(
        item, b"\xff\xd8working\xff\xd9"
    )
    await wall.close()


@pytest.mark.asyncio
async def test_preview_wall_ignores_delayed_error_from_replaced_subscription() -> None:
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    old_preview = FakePreview()

    async def slow_close() -> None:
        close_started.set()
        await allow_close.wait()
        old_preview.closed += 1

    old_preview.close = slow_close  # type: ignore[method-assign]

    async def open_source(item, _profile):
        if item.subscription_id == 40:
            return OpenedPreview(
                preview=old_preview,
                release=lambda: None,
            )
        raise LivePreviewError(
            "replacement_failed", "Replacement failed."
        )

    wall = PreviewWallSession(open_source)
    old = subscription(0, 40)
    replacement = subscription(0, 41)
    await wall.apply_sync(PreviewWallSync(9, (old,)))
    await asyncio.sleep(0)

    delayed_failure = asyncio.create_task(
        wall.fail_subscription(
            old,
            code="old_revoked",
            message="Old subscription was revoked.",
        )
    )
    await asyncio.wait_for(close_started.wait(), 1)
    await wall.apply_sync(PreviewWallSync(9, (replacement,)))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    allow_close.set()
    await asyncio.wait_for(delayed_failure, 1)

    errors: list[dict[str, object]] = []
    for _ in range(3):
        message = await asyncio.wait_for(wall.next_message(), 1)
        if isinstance(message, str):
            payload = json.loads(message)
            if payload.get("type") == "error":
                errors.append(payload)
        if errors:
            break

    assert errors == [
        {
            "type": "error",
            "slot": 0,
            "subscription_id": 41,
            "code": "replacement_failed",
            "message": "Replacement failed.",
        }
    ]
    await wall.close()


@pytest.mark.asyncio
async def test_preview_wall_session_isolates_failure_and_closes_all() -> None:
    opened: dict[int, FakePreview] = {}
    released: list[int] = []

    async def open_source(item, _profile):
        preview = FakePreview()
        opened[item.slot] = preview
        return OpenedPreview(
            preview=preview,
            release=lambda: released.append(item.slot),
        )

    wall = PreviewWallSession(open_source)
    zero = subscription(0, 30)
    one = subscription(1, 31)
    await wall.apply_sync(PreviewWallSync(4, (zero, one)))
    await wait_until(lambda: len(opened) == 2)
    await opened[0].queue.put(
        LivePreviewError("camera_offline", "Camera is offline.")
    )
    await opened[1].queue.put(b"\xff\xd8working\xff\xd9")

    messages: list[str | bytes] = []
    while True:
        messages.append(await asyncio.wait_for(wall.next_message(), 1))
        decoded_so_far = [
            json.loads(item)
            for item in messages
            if isinstance(item, str)
        ]
        if any(isinstance(item, bytes) for item in messages) and any(
            item.get("type") == "error" for item in decoded_so_far
        ):
            break

    decoded = [
        json.loads(item)
        for item in messages
        if isinstance(item, str)
    ]
    assert any(
        item.get("type") == "error"
        and item.get("slot") == 0
        and item.get("subscription_id") == 30
        and item.get("code") == "camera_offline"
        for item in decoded
    )
    assert any(
        isinstance(item, bytes) and item[1] == 1
        for item in messages
    )

    await wall.close()
    assert opened[0].closed == 1
    assert opened[1].closed == 1
    assert sorted(released) == [0, 1]
