from __future__ import annotations

import asyncio
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


_cleanup_tasks: set[asyncio.Task[None]] = set()


class LivePreviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    return [
        settings.ffmpeg_binary,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-fflags",
        "nobuffer",
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
        "mpjpeg",
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
    first_chunk: bytes
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

    async def stream(self) -> AsyncIterator[bytes]:
        try:
            yield self.first_chunk
            assert self.process.stdout is not None
            while True:
                chunk = await self.process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            await self.close()


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
    try:
        first_chunk = await asyncio.wait_for(
            process.stdout.read(64 * 1024),
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

    if not first_chunk:
        await _stop_process(process)
        raise LivePreviewError(
            "live_preview_start_failed",
            "Fast live preview did not become ready.",
        )

    return LivePreviewSession(
        process=process,
        first_chunk=first_chunk,
    )
