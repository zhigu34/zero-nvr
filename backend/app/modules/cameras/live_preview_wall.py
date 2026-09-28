from __future__ import annotations

import asyncio
import json
import uuid
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Literal

from .live_preview import (
    MAX_PREVIEW_FRAME_BYTES,
    LivePreviewError,
    LivePreviewSession,
)


PREVIEW_WALL_PROTOCOL_VERSION = 1
MAX_SYNC_BYTES = 64 * 1024
MAX_STREAMS = 16


class PreviewWallProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PreviewWallProfile:
    width: int
    fps: int


@dataclass(frozen=True, slots=True)
class PreviewWallSubscription:
    slot: int
    subscription_id: int
    camera_id: uuid.UUID
    media_session_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class PreviewWallSync:
    layout_slots: Literal[4, 9, 16]
    streams: tuple[PreviewWallSubscription, ...]


_PROFILES = {
    4: PreviewWallProfile(width=640, fps=5),
    6: PreviewWallProfile(width=640, fps=5),
    9: PreviewWallProfile(width=480, fps=3),
    16: PreviewWallProfile(width=320, fps=2),
}


def _protocol_error(message: str) -> PreviewWallProtocolError:
    return PreviewWallProtocolError("invalid_sync", message)


def preview_wall_profile(layout_slots: int) -> PreviewWallProfile:
    try:
        return _PROFILES[layout_slots]
    except (KeyError, TypeError) as exc:
        raise _protocol_error("Unsupported preview wall layout.") from exc


def _required_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _protocol_error(f"{name} must be an integer.")
    return value


def _required_uuid(value: object, name: str) -> uuid.UUID:
    if not isinstance(value, str):
        raise _protocol_error(f"{name} must be a UUID.")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise _protocol_error(f"{name} must be a UUID.") from exc


def parse_preview_wall_sync(raw: str) -> PreviewWallSync:
    if len(raw.encode("utf-8")) > MAX_SYNC_BYTES:
        raise _protocol_error("Preview wall sync is too large.")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _protocol_error("Preview wall sync is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise _protocol_error("Preview wall sync must be an object.")
    if payload.get("type") != "sync":
        raise _protocol_error("Unsupported preview wall message type.")
    if _required_int(payload.get("version"), "version") != 1:
        raise _protocol_error("Unsupported preview wall protocol version.")

    layout_slots = _required_int(
        payload.get("layout_slots"), "layout_slots"
    )
    preview_wall_profile(layout_slots)
    raw_streams = payload.get("streams")
    if not isinstance(raw_streams, list):
        raise _protocol_error("streams must be an array.")
    if len(raw_streams) > MAX_STREAMS:
        raise _protocol_error("Too many preview wall streams.")

    streams: list[PreviewWallSubscription] = []
    seen_slots: set[int] = set()
    for raw_stream in raw_streams:
        if not isinstance(raw_stream, dict):
            raise _protocol_error("Each stream must be an object.")
        slot = _required_int(raw_stream.get("slot"), "slot")
        if slot < 0 or slot >= layout_slots or slot in seen_slots:
            raise _protocol_error("Stream slots must be unique and in range.")
        seen_slots.add(slot)
        subscription_id = _required_int(
            raw_stream.get("subscription_id"), "subscription_id"
        )
        if subscription_id < 0 or subscription_id > 0xFFFFFFFF:
            raise _protocol_error("subscription_id must be uint32.")
        streams.append(
            PreviewWallSubscription(
                slot=slot,
                subscription_id=subscription_id,
                camera_id=_required_uuid(
                    raw_stream.get("camera_id"), "camera_id"
                ),
                media_session_id=_required_uuid(
                    raw_stream.get("media_session_id"),
                    "media_session_id",
                ),
            )
        )

    return PreviewWallSync(
        layout_slots=layout_slots,  # type: ignore[arg-type]
        streams=tuple(streams),
    )


def encode_preview_wall_frame(
    subscription: PreviewWallSubscription,
    jpeg: bytes,
) -> bytes:
    if (
        len(jpeg) > MAX_PREVIEW_FRAME_BYTES
        or not jpeg.startswith(b"\xff\xd8")
        or not jpeg.endswith(b"\xff\xd9")
    ):
        raise LivePreviewError(
            "live_preview_invalid_frame",
            "Fast live preview produced an invalid JPEG frame.",
        )
    return bytes(
        (PREVIEW_WALL_PROTOCOL_VERSION, subscription.slot)
    ) + subscription.subscription_id.to_bytes(4, "big") + jpeg


@dataclass(frozen=True, slots=True)
class OpenedPreview:
    preview: LivePreviewSession
    release: Callable[[], None]


@dataclass(slots=True)
class _ActivePreview:
    subscription: PreviewWallSubscription
    profile: PreviewWallProfile
    task: asyncio.Task[None] | None = None
    opened: OpenedPreview | None = None
    cleaned: bool = False
    ready_sent: bool = False


OpenSource = Callable[
    [PreviewWallSubscription, PreviewWallProfile],
    Awaitable[OpenedPreview],
]


class PreviewWallSession:
    def __init__(self, open_source: OpenSource) -> None:
        self._open_source = open_source
        self._entries: dict[int, _ActivePreview] = {}
        self._desired: dict[int, PreviewWallSubscription] = {}
        self._control: OrderedDict[tuple[str, int], str] = (
            OrderedDict()
        )
        self._latest_frames: dict[
            int, tuple[PreviewWallSubscription, bytes]
        ] = {}
        self._ready_slots: deque[int] = deque()
        self._ready_set: set[int] = set()
        self._wake = asyncio.Event()
        self._closed = False
        self._last_message_was_control = False

    def _queue_event(self, payload: dict[str, Any]) -> None:
        slot = payload.get("slot")
        subscription_id = payload.get("subscription_id")
        if isinstance(slot, int) and isinstance(subscription_id, int):
            desired = self._desired.get(slot)
            if (
                desired is None
                or desired.subscription_id != subscription_id
            ):
                return
        key = (
            ("slot", slot)
            if isinstance(slot, int)
            else (str(payload.get("type", "event")), -1)
        )
        self._control[key] = json.dumps(
            payload, separators=(",", ":")
        )
        self._control.move_to_end(key)
        self._wake.set()

    def _discard_pending(self, slot: int) -> None:
        self._latest_frames.pop(slot, None)
        if slot in self._ready_set:
            self._ready_set.discard(slot)
            self._ready_slots = deque(
                ready for ready in self._ready_slots if ready != slot
            )

    async def _cleanup_entry(self, entry: _ActivePreview) -> None:
        if entry.cleaned:
            return
        entry.cleaned = True
        if entry.opened is not None:
            with suppress(Exception):
                await entry.opened.preview.close()
            with suppress(Exception):
                entry.opened.release()

    async def _run_source(self, entry: _ActivePreview) -> None:
        subscription = entry.subscription
        ended_normally = False
        try:
            opened = await self._open_source(
                subscription, entry.profile
            )
            entry.opened = opened
            if self._entries.get(subscription.slot) is not entry:
                return
            async for jpeg in opened.preview.frames():
                encoded = encode_preview_wall_frame(
                    subscription, jpeg
                )
                if self._entries.get(subscription.slot) is not entry:
                    break
                if not entry.ready_sent:
                    entry.ready_sent = True
                    self._queue_event(
                        {
                            "type": "ready",
                            "slot": subscription.slot,
                            "subscription_id": (
                                subscription.subscription_id
                            ),
                        }
                    )
                self._latest_frames[subscription.slot] = (
                    subscription,
                    encoded,
                )
                if subscription.slot not in self._ready_set:
                    self._ready_set.add(subscription.slot)
                    self._ready_slots.append(subscription.slot)
                self._wake.set()
            ended_normally = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._entries.get(subscription.slot) is entry:
                code = getattr(exc, "code", "live_preview_failed")
                self._queue_event(
                    {
                        "type": "error",
                        "slot": subscription.slot,
                        "subscription_id": subscription.subscription_id,
                        "code": str(code),
                        "message": str(exc),
                    }
                )
        finally:
            if (
                ended_normally
                and self._entries.get(subscription.slot) is entry
            ):
                self._queue_event(
                    {
                        "type": "error",
                        "slot": subscription.slot,
                        "subscription_id": subscription.subscription_id,
                        "code": "live_preview_ended",
                        "message": "Fast live preview ended.",
                    }
                )
            if self._entries.get(subscription.slot) is entry:
                self._entries.pop(subscription.slot, None)
                self._discard_pending(subscription.slot)
            await self._cleanup_entry(entry)

    async def _stop_entry(self, entry: _ActivePreview) -> None:
        if entry.task is not None and not entry.task.done():
            entry.task.cancel()
            with suppress(asyncio.CancelledError):
                await entry.task
        await self._cleanup_entry(entry)

    async def apply_sync(self, sync: PreviewWallSync) -> None:
        if self._closed:
            raise RuntimeError("Preview wall session is closed.")
        profile = preview_wall_profile(sync.layout_slots)
        desired = {item.slot: item for item in sync.streams}
        self._desired = desired.copy()

        for slot, entry in list(self._entries.items()):
            if (
                desired.get(slot) == entry.subscription
                and entry.profile == profile
            ):
                continue
            self._entries.pop(slot, None)
            self._discard_pending(slot)
            await self._stop_entry(entry)

        for slot, item in desired.items():
            if slot in self._entries:
                continue
            entry = _ActivePreview(
                subscription=item,
                profile=profile,
            )
            self._entries[slot] = entry
            entry.task = asyncio.create_task(self._run_source(entry))

        self._queue_event(
            {"type": "synced", "version": PREVIEW_WALL_PROTOCOL_VERSION}
        )

    async def next_message(self) -> str | bytes:
        while True:
            if self._control and (
                not self._ready_slots
                or not self._last_message_was_control
            ):
                self._last_message_was_control = True
                return self._control.popitem(last=False)[1]
            while self._ready_slots:
                slot = self._ready_slots.popleft()
                self._ready_set.discard(slot)
                pending = self._latest_frames.pop(slot, None)
                if pending is None:
                    continue
                subscription, encoded = pending
                entry = self._entries.get(slot)
                if entry is None or entry.subscription != subscription:
                    continue
                self._last_message_was_control = False
                return encoded
            self._wake.clear()
            if self._control or self._ready_slots:
                continue
            await self._wake.wait()

    async def fail_subscription(
        self,
        subscription: PreviewWallSubscription,
        *,
        code: str,
        message: str,
    ) -> None:
        entry = self._entries.get(subscription.slot)
        if entry is None or entry.subscription != subscription:
            return
        self._entries.pop(subscription.slot, None)
        self._discard_pending(subscription.slot)
        await self._stop_entry(entry)
        self._queue_event(
            {
                "type": "error",
                "slot": subscription.slot,
                "subscription_id": subscription.subscription_id,
                "code": code,
                "message": message,
            }
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        entries = list(self._entries.values())
        self._entries.clear()
        self._desired.clear()
        self._latest_frames.clear()
        self._ready_slots.clear()
        self._ready_set.clear()
        for entry in entries:
            await self._stop_entry(entry)
        self._wake.set()
