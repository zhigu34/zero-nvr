from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.config import Settings

try:
    from app.modules.cameras.live_preview import (
        LivePreviewError,
        build_live_preview_command,
        open_live_preview,
    )
except ModuleNotFoundError:
    LivePreviewError = None
    build_live_preview_command = None
    open_live_preview = None


def settings(tmp_path: Path) -> Settings:
    return Settings(
        secret_key="live-preview-test-secret-key-32-bytes-minimum",
        environment="test",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )


class FakeStdout:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)

    async def read(self, _size: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


class FakeProcess:
    def __init__(self, chunks: list[bytes]) -> None:
        self.stdout = FakeStdout(chunks)
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class BlockingStdout:
    async def read(self, _size: int) -> bytes:
        await asyncio.Event().wait()
        return b""


class StubbornProcess(FakeProcess):
    def __init__(self) -> None:
        super().__init__([b""])
        self.stdout = BlockingStdout()
        self._exited = asyncio.Event()

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self._exited.set()

    async def wait(self) -> int:
        await self._exited.wait()
        return -9


def test_preview_command_is_low_latency_and_bounded(
    tmp_path: Path,
) -> None:
    assert build_live_preview_command is not None

    command = build_live_preview_command(
        settings(tmp_path),
        source_url="rtsp://zlmediakit:554/zero-nvr/source",
        width=4000,
        fps=50,
    )

    assert command[0] == "ffmpeg"
    assert command[command.index("-rtsp_transport") + 1] == "tcp"
    assert "nobuffer" in command
    assert "low_delay" in command
    assert command[command.index("-vf") + 1] == (
        "fps=8,scale='min(1280,iw)':-2"
    )
    assert command[command.index("-c:v") + 1] == "mjpeg"
    assert command[-3:] == ["-f", "mpjpeg", "pipe:1"]

    minimum = build_live_preview_command(
        settings(tmp_path),
        source_url="rtsp://zlmediakit:554/zero-nvr/source",
        width=1,
        fps=0,
    )
    assert minimum[minimum.index("-vf") + 1] == (
        "fps=1,scale='min(320,iw)':-2"
    )


@pytest.mark.asyncio
async def test_preview_stream_yields_first_chunk_and_stops_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    assert open_live_preview is not None
    process = FakeProcess([b"first-jpeg", b"second-jpeg"])
    commands: list[tuple[object, ...]] = []

    async def create_subprocess(*command, **kwargs):
        commands.append(command)
        assert kwargs["stdout"] is not None
        return process

    monkeypatch.setattr(
        "app.modules.cameras.live_preview.asyncio.create_subprocess_exec",
        create_subprocess,
    )

    preview = await open_live_preview(
        settings(tmp_path),
        source_url="rtsp://zlmediakit:554/zero-nvr/source",
        width=640,
        fps=5,
    )
    stream = preview.stream()

    assert await anext(stream) == b"first-jpeg"
    assert await anext(stream) == b"second-jpeg"
    await stream.aclose()

    assert commands
    assert process.terminated
    assert not process.killed


@pytest.mark.asyncio
async def test_preview_start_rejects_empty_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    assert open_live_preview is not None
    assert LivePreviewError is not None
    process = FakeProcess([b""])

    async def create_subprocess(*_command, **_kwargs):
        return process

    monkeypatch.setattr(
        "app.modules.cameras.live_preview.asyncio.create_subprocess_exec",
        create_subprocess,
    )

    with pytest.raises(LivePreviewError) as caught:
        await open_live_preview(
            settings(tmp_path),
            source_url="rtsp://zlmediakit:554/zero-nvr/source",
            width=640,
            fps=5,
        )

    assert caught.value.code == "live_preview_start_failed"
    assert process.terminated


@pytest.mark.asyncio
async def test_preview_start_cancellation_stops_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    assert open_live_preview is not None
    process = FakeProcess([])
    process.stdout = BlockingStdout()

    async def create_subprocess(*_command, **_kwargs):
        return process

    monkeypatch.setattr(
        "app.modules.cameras.live_preview.asyncio.create_subprocess_exec",
        create_subprocess,
    )

    startup = asyncio.create_task(
        open_live_preview(
            settings(tmp_path),
            source_url="rtsp://zlmediakit:554/zero-nvr/source",
            width=640,
            fps=5,
        )
    )
    await asyncio.sleep(0)
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    await asyncio.sleep(0)

    assert process.terminated


@pytest.mark.asyncio
async def test_cancelled_stream_cleanup_escalates_to_kill(
    monkeypatch,
) -> None:
    from app.modules.cameras import live_preview

    assert live_preview.LivePreviewSession is not None
    monkeypatch.setattr(
        live_preview,
        "PREVIEW_STOP_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )
    process = StubbornProcess()
    preview = live_preview.LivePreviewSession(
        process=process,
        first_chunk=b"first-jpeg",
    )
    stream = preview.stream()
    assert await anext(stream) == b"first-jpeg"

    closing = asyncio.create_task(stream.aclose())
    await asyncio.sleep(0)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await asyncio.sleep(0.05)

    assert process.terminated
    assert process.killed
    assert process.returncode == -9
