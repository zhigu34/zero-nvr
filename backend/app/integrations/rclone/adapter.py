from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class RcloneIntegrationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class RcloneStat:
    path: str
    size_bytes: int


class RcloneAdapter:
    """Focused rclone boundary for immutable recording objects.

    Secret rclone config is materialized only for the duration of a command.
    Raw rclone stderr/stdout is never included in raised exceptions because
    some backends may echo endpoint/account details.
    """

    def __init__(
        self,
        *,
        config_text: str,
        binary: str = "rclone",
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout_seconds: float = 300.0,
    ) -> None:
        if not config_text.strip():
            raise RcloneIntegrationError(
                "rclone_config_missing",
                "rclone configuration is unavailable.",
                status_code=503,
            )
        self._config_text = config_text
        self._binary = binary
        self._runner = runner
        self._timeout_seconds = timeout_seconds

    def _run(
        self,
        args: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        config_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="zero-nvr-rclone-",
                suffix=".conf",
                delete=False,
            ) as handle:
                config_path = handle.name
                os.chmod(config_path, 0o600)
                handle.write(self._config_text)
                handle.flush()
                os.fsync(handle.fileno())

            try:
                return self._runner(
                    [
                        self._binary,
                        *args,
                        "--config",
                        config_path,
                        "--log-level",
                        "ERROR",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=(
                        timeout_seconds
                        if timeout_seconds is not None
                        else self._timeout_seconds
                    ),
                )
            except FileNotFoundError as exc:
                raise RcloneIntegrationError(
                    "rclone_unavailable",
                    "rclone executable is not available.",
                    status_code=503,
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise RcloneIntegrationError(
                    "rclone_timeout",
                    "rclone operation did not complete in time.",
                    status_code=504,
                ) from exc
            except subprocess.CalledProcessError as exc:
                raise RcloneIntegrationError(
                    "rclone_operation_failed",
                    "rclone operation failed.",
                ) from exc
        finally:
            if config_path is not None:
                try:
                    Path(config_path).unlink(missing_ok=True)
                except OSError:
                    pass

    def copy_to_remote(
        self,
        *,
        source: Path,
        destination: str,
        expected_size: int,
    ) -> RcloneStat:
        if not source.is_file():
            raise RcloneIntegrationError(
                "archive_source_missing",
                "Recording source file is unavailable.",
                status_code=409,
            )

        self._run(
            [
                "copyto",
                str(source),
                destination,
                "--no-traverse",
            ]
        )
        stat = self.stat(destination)
        if stat.size_bytes != expected_size:
            raise RcloneIntegrationError(
                "rclone_size_mismatch",
                "Archived object size verification failed.",
                status_code=409,
            )
        return stat

    def copy_to_local(
        self,
        *,
        source: str,
        destination: Path,
        expected_size: int | None = None,
    ) -> RcloneStat:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".partial")
        partial.unlink(missing_ok=True)
        try:
            self._run(
                [
                    "copyto",
                    source,
                    str(partial),
                    "--no-traverse",
                ]
            )
            size = partial.stat().st_size
            if expected_size is not None and size != expected_size:
                raise RcloneIntegrationError(
                    "rclone_size_mismatch",
                    "Restored object size verification failed.",
                    status_code=409,
                )
            os.replace(partial, destination)
            return RcloneStat(
                path=str(destination),
                size_bytes=size,
            )
        finally:
            partial.unlink(missing_ok=True)

    def stat(self, remote_path: str) -> RcloneStat:
        completed = self._run(
            [
                "lsjson",
                remote_path,
                "--stat",
                "--no-modtime",
                "--no-mimetype",
            ],
            timeout_seconds=min(self._timeout_seconds, 60.0),
        )
        try:
            payload = json.loads(completed.stdout)
            if not isinstance(payload, dict):
                raise ValueError
            if bool(payload.get("IsDir")):
                raise ValueError
            size = int(payload["Size"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise RcloneIntegrationError(
                "rclone_invalid_response",
                "rclone returned invalid object metadata.",
            ) from exc
        if size < 0:
            raise RcloneIntegrationError(
                "rclone_invalid_response",
                "rclone returned invalid object metadata.",
            )
        return RcloneStat(
            path=remote_path,
            size_bytes=size,
        )

    def delete_file(self, remote_path: str) -> None:
        self._run(["deletefile", remote_path])
