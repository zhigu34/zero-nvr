from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.core.config import Settings


ReleaseValidationKind = Literal[
    "benchmark",
    "soak",
]
ReleaseValidationState = Literal[
    "AVAILABLE",
    "MISSING",
    "INVALID",
]


@dataclass(frozen=True, slots=True)
class ReleaseValidationArtifact:
    kind: ReleaseValidationKind
    state: ReleaseValidationState
    command: str
    updated_at: datetime | None = None
    report: dict[str, object] | None = None
    error_code: str | None = None


class ReleaseValidationReportService:
    max_report_bytes = 2 * 1024 * 1024
    commands = {
        "benchmark": (
            "./deploy.sh benchmark <8|16> "
            "[--samples N] [--interval SECONDS]"
        ),
        "soak": (
            "./deploy.sh soak <8|16> "
            "[--duration SECONDS] [--interval SECONDS]"
        ),
    }

    def __init__(self, settings: Settings) -> None:
        self.root = (
            settings.data_dir
            / "release-validation"
        )

    def _path(
        self,
        kind: ReleaseValidationKind,
    ) -> Path:
        return self.root / f"latest-{kind}.json"

    @staticmethod
    def _invalid(
        kind: ReleaseValidationKind,
        *,
        updated_at: datetime | None,
        error_code: str,
    ) -> ReleaseValidationArtifact:
        return ReleaseValidationArtifact(
            kind=kind,
            state="INVALID",
            command=(
                ReleaseValidationReportService
                .commands[kind]
            ),
            updated_at=updated_at,
            error_code=error_code,
        )

    def read(
        self,
        kind: ReleaseValidationKind,
    ) -> ReleaseValidationArtifact:
        path = self._path(kind)
        try:
            stat = path.stat()
        except FileNotFoundError:
            return ReleaseValidationArtifact(
                kind=kind,
                state="MISSING",
                command=self.commands[kind],
            )
        except OSError:
            return self._invalid(
                kind,
                updated_at=None,
                error_code=(
                    "release_validation_report_unavailable"
                ),
            )

        updated_at = datetime.fromtimestamp(
            stat.st_mtime,
            tz=UTC,
        )
        if (
            not path.is_file()
            or stat.st_size <= 0
            or stat.st_size > self.max_report_bytes
        ):
            return self._invalid(
                kind,
                updated_at=updated_at,
                error_code=(
                    "release_validation_report_invalid"
                ),
            )

        try:
            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return self._invalid(
                kind,
                updated_at=updated_at,
                error_code=(
                    "release_validation_report_invalid"
                ),
            )

        if (
            not isinstance(payload, dict)
            or not isinstance(
                payload.get("profile"),
                str,
            )
            or not isinstance(
                payload.get("passed"),
                bool,
            )
        ):
            return self._invalid(
                kind,
                updated_at=updated_at,
                error_code=(
                    "release_validation_report_invalid"
                ),
            )

        return ReleaseValidationArtifact(
            kind=kind,
            state="AVAILABLE",
            command=self.commands[kind],
            updated_at=updated_at,
            report=payload,
        )

    def collect(
        self,
    ) -> tuple[
        ReleaseValidationArtifact,
        ReleaseValidationArtifact,
    ]:
        return (
            self.read("benchmark"),
            self.read("soak"),
        )
