from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class ResticIntegrationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResticBackupResult:
    snapshot_id: str
    size_bytes: int | None


class ResticAdapter:
    def __init__(
        self,
        *,
        repository: str,
        password: str,
        environment: Mapping[str, str] | None = None,
        binary: str = "restic",
        timeout_seconds: float = 3600.0,
    ) -> None:
        if not repository.strip():
            raise ValueError("restic repository is required")
        if not password:
            raise ValueError("restic password is required")

        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self._env = os.environ.copy()
        self._env["RESTIC_REPOSITORY"] = repository
        self._env["RESTIC_PASSWORD"] = password

        for key, value in (environment or {}).items():
            if (
                not _ENV_KEY.match(key)
                or key in {
                    "RESTIC_REPOSITORY",
                    "RESTIC_PASSWORD",
                    "RESTIC_PASSWORD_FILE",
                }
            ):
                raise ValueError(
                    "restic environment contains an invalid key"
                )
            self._env[key] = value

    def _run(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.binary, *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout_seconds,
                env=self._env,
            )
        except subprocess.TimeoutExpired as exc:
            raise ResticIntegrationError(
                "restic_timeout",
                "restic operation timed out.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise ResticIntegrationError(
                "restic_operation_failed",
                "restic operation failed.",
            ) from exc

    def ensure_repository(
        self,
        *,
        initialize_if_missing: bool,
    ) -> None:
        try:
            self._run(
                ["snapshots", "--json", "--latest", "1"],
                timeout=min(self.timeout_seconds, 60.0),
            )
            return
        except ResticIntegrationError:
            if not initialize_if_missing:
                raise

        try:
            self._run(
                ["init"],
                timeout=min(self.timeout_seconds, 120.0),
            )
        except ResticIntegrationError as exc:
            raise ResticIntegrationError(
                "restic_repository_unavailable",
                "restic repository is unavailable or could not be initialized.",
            ) from exc

    @staticmethod
    def _summary(stdout: str) -> dict[str, object]:
        summary: dict[str, object] = {}
        for line in stdout.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(value, dict)
                and value.get("message_type") == "summary"
            ):
                summary = value
        return summary

    def backup(
        self,
        *,
        paths: list[Path],
        tags: list[str],
    ) -> ResticBackupResult:
        if not paths:
            raise ResticIntegrationError(
                "restic_backup_empty",
                "No backup payload paths were provided.",
            )

        args = ["backup", "--json"]
        for tag in tags:
            args.extend(["--tag", tag])
        args.extend(str(path) for path in paths)

        completed = self._run(args)
        summary = self._summary(completed.stdout)
        snapshot_id = summary.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            snapshots = self._run(
                ["snapshots", "--json", "--latest", "1"]
            )
            try:
                rows = json.loads(snapshots.stdout)
            except json.JSONDecodeError as exc:
                raise ResticIntegrationError(
                    "restic_invalid_response",
                    "restic returned an invalid snapshot response.",
                ) from exc
            if (
                not isinstance(rows, list)
                or not rows
                or not isinstance(rows[-1], dict)
                or not isinstance(rows[-1].get("id"), str)
            ):
                raise ResticIntegrationError(
                    "restic_snapshot_missing",
                    "restic did not report the created snapshot.",
                )
            snapshot_id = rows[-1]["id"]

        raw_size = summary.get("data_added")
        size_bytes = (
            int(raw_size)
            if isinstance(raw_size, (int, float))
            and raw_size >= 0
            else None
        )
        return ResticBackupResult(
            snapshot_id=snapshot_id,
            size_bytes=size_bytes,
        )

    def check(self) -> None:
        self._run(["check"])

    def forget(
        self,
        retention: Mapping[str, int],
    ) -> None:
        allowed = {
            "keep_last": "--keep-last",
            "keep_daily": "--keep-daily",
            "keep_weekly": "--keep-weekly",
            "keep_monthly": "--keep-monthly",
            "keep_yearly": "--keep-yearly",
        }
        args = ["forget", "--prune"]
        for key, flag in allowed.items():
            value = retention.get(key)
            if value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > 10000
            ):
                raise ResticIntegrationError(
                    "restic_retention_invalid",
                    "restic retention policy is invalid.",
                )
            args.extend([flag, str(value)])
        self._run(args)
