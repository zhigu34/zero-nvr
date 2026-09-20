from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FfmpegExportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FfmpegInputClip:
    file_path: Path
    inpoint_seconds: float
    outpoint_seconds: float
    codec: str | None


@dataclass(frozen=True, slots=True)
class FfmpegExportResult:
    output_path: Path
    size_bytes: int
    duration_ms: int
    codec_mode: str


class FfmpegExportAdapter:
    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        timeout_seconds: float = 3600.0,
    ) -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def effective_codec_mode(
        requested: str,
        clips: list[FfmpegInputClip],
    ) -> str:
        if requested not in {"auto", "copy", "h264"}:
            raise FfmpegExportError(
                "export_codec_mode_invalid",
                "Export codec mode is invalid.",
            )
        if requested != "auto":
            return requested

        codecs = {
            (clip.codec or "").strip().lower()
            for clip in clips
        }
        if codecs and codecs <= {
            "h264",
            "avc",
            "avc1",
        }:
            return "copy"
        return "h264"

    @staticmethod
    def _concat_quote(path: Path) -> str:
        value = str(path)
        return "'" + value.replace("'", "'\\''") + "'"

    def _manifest(
        self,
        *,
        clips: list[FfmpegInputClip],
        path: Path,
    ) -> None:
        lines = ["ffconcat version 1.0"]
        for clip in clips:
            if clip.outpoint_seconds <= clip.inpoint_seconds:
                raise FfmpegExportError(
                    "export_clip_invalid",
                    "Export clip range is invalid.",
                )
            lines.append(
                f"file {self._concat_quote(clip.file_path)}"
            )
            lines.append(
                f"inpoint {clip.inpoint_seconds:.6f}"
            )
            lines.append(
                f"outpoint {clip.outpoint_seconds:.6f}"
            )
        path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    def _probe_duration_ms(self, path: Path) -> int:
        try:
            completed = subprocess.run(
                [
                    self.ffprobe_binary,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=min(self.timeout_seconds, 60.0),
            )
            payload = json.loads(completed.stdout)
            duration = float(
                (payload.get("format") or {}).get("duration")
                or 0
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise FfmpegExportError(
                "export_probe_failed",
                "Unable to verify the exported media.",
            ) from exc

        if duration < 0:
            raise FfmpegExportError(
                "export_probe_failed",
                "Exported media duration is invalid.",
            )
        return int(round(duration * 1000))

    def render(
        self,
        *,
        clips: list[FfmpegInputClip],
        output_path: Path,
        codec_mode: str,
    ) -> FfmpegExportResult:
        if not clips:
            raise FfmpegExportError(
                "export_media_unavailable",
                "No media clips were selected for export.",
            )

        for clip in clips:
            if not clip.file_path.is_file():
                raise FfmpegExportError(
                    "export_source_missing",
                    "An export source file is unavailable.",
                )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        manifest = output_path.with_suffix(
            ".ffconcat"
        )
        partial = output_path.with_name(
            output_path.stem
            + ".partial"
            + output_path.suffix
        )
        self._manifest(
            clips=clips,
            path=manifest,
        )

        effective = self.effective_codec_mode(
            codec_mode,
            clips,
        )
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
        ]
        if effective == "copy":
            command.extend(
                [
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                ]
            )
        else:
            command.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-movflags",
                    "+faststart",
                ]
            )
        command.append(str(partial))

        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            if not partial.is_file():
                raise FfmpegExportError(
                    "export_output_missing",
                    "FFmpeg did not produce an export file.",
                )
            duration_ms = self._probe_duration_ms(
                partial
            )
            size_bytes = partial.stat().st_size
            os.replace(partial, output_path)
        except subprocess.TimeoutExpired as exc:
            raise FfmpegExportError(
                "export_timeout",
                "Export processing timed out.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise FfmpegExportError(
                "export_ffmpeg_failed",
                "FFmpeg could not create the export.",
            ) from exc
        finally:
            manifest.unlink(missing_ok=True)
            if partial.exists():
                partial.unlink(missing_ok=True)

        return FfmpegExportResult(
            output_path=output_path,
            size_bytes=size_bytes,
            duration_ms=duration_ms,
            codec_mode=effective,
        )
