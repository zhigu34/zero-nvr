from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import app.integrations.ffmpeg.adapter as ffmpeg_module
from app.integrations.ffmpeg import (
    FfmpegExportAdapter,
    FfmpegExportError,
    FfmpegInputClip,
)


def clip(path: Path, codec: str) -> FfmpegInputClip:
    path.write_bytes(b"source")
    return FfmpegInputClip(
        file_path=path,
        inpoint_seconds=1.0,
        outpoint_seconds=6.0,
        codec=codec,
    )


def test_auto_h264_uses_stream_copy_and_atomic_publish(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"exported")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=b"",
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"format":{"duration":"5.125"}}',
            stderr="",
        )

    monkeypatch.setattr(
        ffmpeg_module.subprocess,
        "run",
        fake_run,
    )
    output = tmp_path / "out.mp4"
    adapter = FfmpegExportAdapter()

    result = adapter.render(
        clips=[clip(tmp_path / "source.mp4", "h264")],
        output_path=output,
        codec_mode="auto",
    )

    assert result.codec_mode == "copy"
    assert result.duration_ms == 5125
    assert result.size_bytes == len(b"exported")
    assert output.read_bytes() == b"exported"
    ffmpeg_command = commands[0]
    assert "-c" in ffmpeg_command
    assert "copy" in ffmpeg_command
    assert "libx264" not in ffmpeg_command
    assert not (tmp_path / "out.ffconcat").exists()
    assert not (tmp_path / "out.partial.mp4").exists()


def test_auto_h265_transcodes_to_h264(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"exported")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=b"",
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"format":{"duration":"5"}}',
            stderr="",
        )

    monkeypatch.setattr(
        ffmpeg_module.subprocess,
        "run",
        fake_run,
    )
    adapter = FfmpegExportAdapter()
    result = adapter.render(
        clips=[clip(tmp_path / "source.mp4", "h265")],
        output_path=tmp_path / "out.mp4",
        codec_mode="auto",
    )

    assert result.codec_mode == "h264"
    assert "libx264" in commands[0]


def test_ffmpeg_error_is_sanitized(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "secret-camera-path.mp4"
    source.write_bytes(b"x")

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            command,
            stderr=b"secret-camera-path.mp4 password=oops",
        )

    monkeypatch.setattr(
        ffmpeg_module.subprocess,
        "run",
        fail,
    )

    with pytest.raises(FfmpegExportError) as captured:
        FfmpegExportAdapter().render(
            clips=[
                FfmpegInputClip(
                    file_path=source,
                    inpoint_seconds=0,
                    outpoint_seconds=1,
                    codec="h264",
                )
            ],
            output_path=tmp_path / "out.mp4",
            codec_mode="copy",
        )

    assert captured.value.code == "export_ffmpeg_failed"
    assert "secret-camera-path" not in str(captured.value)
    assert "password" not in str(captured.value)
