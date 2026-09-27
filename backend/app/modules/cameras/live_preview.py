from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Coroutine

from app.core.config import Settings


MIN_PREVIEW_WIDTH = 320
MAX_PREVIEW_WIDTH = 1280
MIN_PREVIEW_FPS = 1
MAX_PREVIEW_FPS = 8
PREVIEW_START_TIMEOUT_SECONDS = 8.0
PREVIEW_STOP_TIMEOUT_SECONDS = 2.0
MAX_PREVIEW_FRAME_BYTES = 2 * 1024 * 1024


_cleanup_tasks: set[asyncio.Task[None]] = set()


class LivePreviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class JpegFrameParser:
    def __init__(
        self,
        max_frame_bytes: int = MAX_PREVIEW_FRAME_BYTES,
    ) -> None:
        if max_frame_bytes < 4:
            raise ValueError("max_frame_bytes must be at least 4")
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buffer.extend(chunk)
        frames: list[bytes] = []
        while True:
            start = self._buffer.find(b"\xff\xd8")
            if start < 0:
                trailing_ff = self._buffer.endswith(b"\xff")
                self._buffer.clear()
                if trailing_ff:
                    self._buffer.append(0xFF)
                return frames
            if start:
                del self._buffer[:start]

            end = self._buffer.find(b"\xff\xd9", 2)
            if end < 0:
                if len(self._buffer) > self.max_frame_bytes:
                    self._buffer.clear()
                    raise LivePreviewError(
                        "live_preview_frame_too_large",
                        "Fast live preview produced an oversized frame.",
                    )
                return frames

            frame_end = end + 2
            if frame_end > self.max_frame_bytes:
                self._buffer.clear()
                raise LivePreviewError(
                    "live_preview_frame_too_large",
                    "Fast live preview produced an oversized frame.",
                )
            frames.append(bytes(self._buffer[:frame_end]))
            del self._buffer[:frame_end]


def build_live_preview_command(
    settings: Settings,
    *,
    source_url: str,
    width: int,
    fps: int,
) -> list[str]:
    bounded_width = max(
        MIN_PREVIEW_WIDTH,
        min(MAX_PREVIEW_WIDTH, width),
    )
    bounded_fps = max(
        MIN_PREVIEW_FPS,
        min(MAX_PREVIEW_FPS, fps),
    )
    # Keep packets read while FFmpeg inspects ZLM's RTSP stream. ZLM may
    # provide the cached H.265 keyframe during that phase; `nobuffer` drops
    # it and can make decoding begin with dependent frames rendered as gray.
    return [
        settings.ffmpeg_binary,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-flags",
        "low_delay",
        "-i",
        source_url,
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        (
            f"fps={bounded_fps},"
            f"scale='min({bounded_width},iw)':-2"
        ),
        "-c:v",
        "mjpeg",
        "-q:v",
        "7",
        "-f",
        "image2pipe",
        "pipe:1",
    ]


def _track_cleanup(
    awaitable: Coroutine[Any, Any, None],
) -> asyncio.Task[None]:
    task = asyncio.create_task(awaitable)
    _cleanup_tasks.add(task)

    def cleanup_done(completed: asyncio.Task[None]) -> None:
        _cleanup_tasks.discard(completed)
        with suppress(asyncio.CancelledError, Exception):
            completed.exception()

    task.add_done_callback(cleanup_done)
    return task


async def _wait_for_process_stop(
    process: asyncio.subprocess.Process,
) -> None:
    try:
        await asyncio.wait_for(
            process.wait(),
            timeout=PREVIEW_STOP_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        if process.returncode is not None:
            return
        with suppress(ProcessLookupError):
            process.kill()
        with suppress(Exception):
            await process.wait()


def _begin_process_stop(
    process: asyncio.subprocess.Process,
) -> asyncio.Task[None] | None:
    if process.returncode is not None:
        return None
    with suppress(ProcessLookupError):
        process.terminate()
    return _track_cleanup(
        _wait_for_process_stop(process)
    )


async def _stop_process(
    process: asyncio.subprocess.Process,
) -> None:
    cleanup = _begin_process_stop(process)
    if cleanup is None:
        return
    await asyncio.shield(cleanup)


@dataclass(slots=True)
class LivePreviewSession:
    process: asyncio.subprocess.Process
    first_frame: bytes
    parser: JpegFrameParser
    pending_frames: deque[bytes] | None = None
    _close_task: asyncio.Task[None] | None = None

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = _begin_process_stop(
                self.process
            )
        if self._close_task is not None:
            await asyncio.shield(self._close_task)

    def close_soon(
        self,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        def schedule() -> None:
            _track_cleanup(self.close())

        with suppress(RuntimeError):
            loop.call_soon_threadsafe(schedule)

    async def frames(self) -> AsyncIterator[bytes]:
        try:
            yield self.first_frame
            if self.pending_frames is not None:
                while self.pending_frames:
                    yield self.pending_frames.popleft()
            assert self.process.stdout is not None
            while True:
                chunk = await self.process.stdout.read(64 * 1024)
                if not chunk:
                    break
                for frame in self.parser.feed(chunk):
                    yield frame
        finally:
            await self.close()


async def multipart_preview_stream(
    frames: AsyncIterator[bytes],
    *,
    boundary: str = "ffmpeg",
) -> AsyncIterator[bytes]:
    boundary_bytes = boundary.encode("ascii")
    async for frame in frames:
        yield (
            b"--"
            + boundary_bytes
            + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(frame)).encode("ascii")
            + b"\r\n\r\n"
            + frame
            + b"\r\n"
        )


async def open_live_preview(
    settings: Settings,
    *,
    source_url: str,
    width: int,
    fps: int,
) -> LivePreviewSession:
    command = build_live_preview_command(
        settings,
        source_url=source_url,
        width=width,
        fps=fps,
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError) as exc:
        raise LivePreviewError(
            "live_preview_spawn_failed",
            "Fast live preview could not be started.",
        ) from exc

    assert process.stdout is not None
    parser = JpegFrameParser()

    async def read_first_frames() -> list[bytes]:
        while True:
            chunk = await process.stdout.read(64 * 1024)
            if not chunk:
                return []
            frames = parser.feed(chunk)
            if frames:
                return frames

    try:
        startup_frames = await asyncio.wait_for(
            read_first_frames(),
            timeout=PREVIEW_START_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        await _stop_process(process)
        raise
    except TimeoutError as exc:
        await _stop_process(process)
        raise LivePreviewError(
            "live_preview_start_failed",
            "Fast live preview did not become ready.",
        ) from exc
    except Exception as exc:
        await _stop_process(process)
        raise LivePreviewError(
            "live_preview_start_failed",
            "Fast live preview did not become ready.",
        ) from exc

    if not startup_frames:
        await _stop_process(process)
        raise LivePreviewError(
            "live_preview_start_failed",
            "Fast live preview did not become ready.",
        )

    return LivePreviewSession(
        process=process,
        first_frame=startup_frames[0],
        parser=parser,
        pending_frames=deque(startup_frames[1:]),
    )
