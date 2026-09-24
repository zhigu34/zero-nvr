from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.modules.backups.models import BackupSet

from .release_validation import (
    ReleaseValidationArtifact,
    ReleaseValidationReportService,
)


@dataclass(frozen=True, slots=True)
class ReleaseReadinessCheck:
    name: str
    passed: bool
    code: str
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReleaseReadiness:
    expected_cameras: int
    checked_at: datetime
    max_age_hours: int
    passed: bool
    checks: tuple[ReleaseReadinessCheck, ...]


BASELINE_SOAK_MIN_DURATION_SECONDS = 60 * 60


class ReleaseReadinessService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
    ) -> None:
        self.database = database
        self.reports = ReleaseValidationReportService(
            settings
        )

    @staticmethod
    def _report_time(
        artifact: ReleaseValidationArtifact,
    ) -> datetime | None:
        report = artifact.report or {}
        raw = report.get("generated_at")
        if isinstance(raw, str):
            normalized = raw.strip()
            if normalized.endswith("Z"):
                normalized = (
                    normalized[:-1] + "+00:00"
                )
            try:
                parsed = datetime.fromisoformat(
                    normalized
                )
            except ValueError:
                parsed = None
            if (
                parsed is not None
                and parsed.tzinfo is not None
            ):
                return parsed.astimezone(UTC)
        return artifact.updated_at

    @classmethod
    def _report_check(
        cls,
        *,
        name: str,
        artifact: ReleaseValidationArtifact,
        expected_profile: str,
        now: datetime,
        max_age: timedelta,
        minimum_duration_seconds: int | None = None,
    ) -> ReleaseReadinessCheck:
        details: dict[str, object] = {
            "state": artifact.state,
            "expected_profile": expected_profile,
        }
        if (
            artifact.state != "AVAILABLE"
            or artifact.report is None
        ):
            return ReleaseReadinessCheck(
                name=name,
                passed=False,
                code=(
                    artifact.error_code
                    or "release_validation_report_missing"
                ),
                details=details,
            )

        report = artifact.report
        profile = report.get("profile")
        generated_at = cls._report_time(
            artifact
        )
        details["profile"] = (
            profile
            if isinstance(profile, str)
            else None
        )
        details["generated_at"] = (
            generated_at.isoformat()
            if generated_at is not None
            else None
        )

        if profile != expected_profile:
            return ReleaseReadinessCheck(
                name=name,
                passed=False,
                code="release_validation_profile_mismatch",
                details=details,
            )
        if report.get("passed") is not True:
            return ReleaseReadinessCheck(
                name=name,
                passed=False,
                code="release_validation_failed",
                details=details,
            )
        if generated_at is None:
            return ReleaseReadinessCheck(
                name=name,
                passed=False,
                code="release_validation_timestamp_missing",
                details=details,
            )

        if minimum_duration_seconds is not None:
            raw_duration = report.get(
                "duration_seconds"
            )
            duration_seconds = (
                raw_duration
                if (
                    isinstance(raw_duration, int)
                    and not isinstance(
                        raw_duration,
                        bool,
                    )
                )
                else None
            )
            details[
                "minimum_duration_seconds"
            ] = minimum_duration_seconds
            details["duration_seconds"] = (
                duration_seconds
            )
            if (
                duration_seconds is None
                or duration_seconds
                < minimum_duration_seconds
            ):
                return ReleaseReadinessCheck(
                    name=name,
                    passed=False,
                    code=(
                        "release_validation_"
                        "duration_insufficient"
                    ),
                    details=details,
                )

        age = now - generated_at
        details["age_seconds"] = max(
            0,
            int(age.total_seconds()),
        )
        if (
            age < timedelta(minutes=-5)
            or age > max_age
        ):
            return ReleaseReadinessCheck(
                name=name,
                passed=False,
                code="release_validation_stale",
                details=details,
            )

        return ReleaseReadinessCheck(
            name=name,
            passed=True,
            code="ok",
            details=details,
        )

    def _backup_check(
        self,
        *,
        now: datetime,
        max_age: timedelta,
    ) -> ReleaseReadinessCheck:
        with self.database.session() as session:
            backup = session.scalar(
                select(BackupSet)
                .where(
                    BackupSet.state == "COMPLETED",
                    BackupSet.verification_state
                    == "PASSED",
                    BackupSet.completed_at.is_not(
                        None
                    ),
                )
                .order_by(
                    BackupSet.completed_at.desc(),
                    BackupSet.id.desc(),
                )
                .limit(1)
            )

        if (
            backup is None
            or backup.completed_at is None
        ):
            return ReleaseReadinessCheck(
                name="verified_backup",
                passed=False,
                code="verified_backup_missing",
                details={},
            )

        completed_at = backup.completed_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(
                tzinfo=UTC
            )
        completed_at = completed_at.astimezone(UTC)
        age = now - completed_at
        details: dict[str, object] = {
            "backup_id": str(backup.id),
            "completed_at": (
                completed_at.isoformat()
            ),
            "age_seconds": max(
                0,
                int(age.total_seconds()),
            ),
            "verification_state": (
                backup.verification_state
            ),
        }
        if (
            age < timedelta(minutes=-5)
            or age > max_age
        ):
            return ReleaseReadinessCheck(
                name="verified_backup",
                passed=False,
                code="verified_backup_stale",
                details=details,
            )

        return ReleaseReadinessCheck(
            name="verified_backup",
            passed=True,
            code="ok",
            details=details,
        )

    def collect(
        self,
        *,
        expected_cameras: int,
        max_age_hours: int = 168,
        now: datetime | None = None,
    ) -> ReleaseReadiness:
        if expected_cameras not in {8, 16}:
            raise ValueError(
                "expected_cameras must be 8 or 16"
            )
        if max_age_hours < 1:
            raise ValueError(
                "max_age_hours must be positive"
            )

        checked_at = (
            now.astimezone(UTC)
            if now is not None
            else datetime.now(UTC)
        )
        max_age = timedelta(
            hours=max_age_hours
        )
        benchmark, soak = self.reports.collect()
        benchmark_profile = (
            "8-camera-baseline"
            if expected_cameras == 8
            else "16-camera-extended"
        )
        benchmark_check = self._report_check(
            name="benchmark",
            artifact=benchmark,
            expected_profile=benchmark_profile,
            now=checked_at,
            max_age=max_age,
        )

        if expected_cameras == 8:
            checks = (
                benchmark_check,
                self._report_check(
                    name="soak",
                    artifact=soak,
                    expected_profile="8-camera-soak",
                    now=checked_at,
                    max_age=max_age,
                    minimum_duration_seconds=(
                        BASELINE_SOAK_MIN_DURATION_SECONDS
                    ),
                ),
                self._backup_check(
                    now=checked_at,
                    max_age=max_age,
                ),
            )
        else:
            checks = (benchmark_check,)
        return ReleaseReadiness(
            expected_cameras=expected_cameras,
            checked_at=checked_at,
            max_age_hours=max_age_hours,
            passed=all(
                item.passed
                for item in checks
            ),
            checks=checks,
        )
