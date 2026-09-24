from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.auth.models import SecretRecord
from app.modules.backups.models import (
    BackupPolicy,
    BackupSet,
)
from app.modules.system.release_readiness import (
    ReleaseReadinessService,
)


def make_database(
    tmp_path: Path,
) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key=(
            "release-readiness-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'ready.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    return settings, database


def write_report(
    settings: Settings,
    *,
    kind: str,
    profile: str,
    passed: bool,
    generated_at: datetime,
    duration_seconds: int | None = None,
) -> None:
    root = (
        settings.data_dir
        / "release-validation"
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / f"latest-{kind}.json").write_text(
        json.dumps(
            {
                "profile": profile,
                "passed": passed,
                "generated_at": (
                    generated_at.isoformat()
                ),
                **(
                    {
                        "duration_seconds": (
                            duration_seconds
                        )
                    }
                    if duration_seconds is not None
                    else {}
                ),
            }
        ),
        encoding="utf-8",
    )


def add_verified_backup(
    database: Database,
    *,
    completed_at: datetime,
) -> uuid.UUID:
    with database.session() as session:
        secret = SecretRecord(
            kind="backup_repository",
            owner_type="backup_policy",
            owner_id=uuid.uuid4(),
            key_id="test",
            encrypted_payload=b"test",
            version=1,
        )
        session.add(secret)
        session.flush()
        policy = BackupPolicy(
            name="Release backup",
            enabled=True,
            repository_config_ref=secret.id,
            credential_secret_ref=None,
            database_backend="sqlite",
            schedule_json={},
            retention_policy_json={},
            verify_after_backup=True,
            repository_check_schedule_json={},
            include_deployment_config=True,
        )
        session.add(policy)
        session.flush()
        backup = BackupSet(
            backup_policy_id=policy.id,
            state="COMPLETED",
            reason="manual",
            schedule_slot=None,
            started_at=(
                completed_at
                - timedelta(minutes=1)
            ),
            completed_at=completed_at,
            app_version="0.1.0",
            schema_revision="test",
            database_engine="sqlite",
            restic_snapshot_id="snapshot-1",
            size_bytes=1024,
            verification_state="PASSED",
            last_verified_at=completed_at,
        )
        session.add(backup)
        session.commit()
        return backup.id


def test_release_readiness_passes_with_matching_fresh_gates(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    now = datetime(
        2026,
        9,
        21,
        1,
        0,
        tzinfo=UTC,
    )
    try:
        write_report(
            settings,
            kind="benchmark",
            profile="8-camera-baseline",
            passed=True,
            generated_at=(
                now - timedelta(hours=1)
            ),
        )
        write_report(
            settings,
            kind="soak",
            profile="8-camera-soak",
            passed=True,
            generated_at=(
                now - timedelta(hours=2)
            ),
            duration_seconds=3600,
        )
        backup_id = add_verified_backup(
            database,
            completed_at=(
                now - timedelta(hours=3)
            ),
        )

        result = ReleaseReadinessService(
            settings,
            database,
        ).collect(
            expected_cameras=8,
            max_age_hours=24,
            now=now,
        )
        assert result.passed is True
        assert [
            item.code
            for item in result.checks
        ] == ["ok", "ok", "ok"]
        assert (
            result.checks[2].details["backup_id"]
            == str(backup_id)
        )
    finally:
        database.close()


def test_release_readiness_rejects_stale_mismatched_or_missing_gates(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    now = datetime(
        2026,
        9,
        21,
        1,
        0,
        tzinfo=UTC,
    )
    try:
        write_report(
            settings,
            kind="benchmark",
            profile="16-camera-baseline",
            passed=True,
            generated_at=(
                now - timedelta(hours=1)
            ),
        )
        write_report(
            settings,
            kind="soak",
            profile="8-camera-soak",
            passed=True,
            generated_at=(
                now - timedelta(days=2)
            ),
            duration_seconds=3600,
        )

        result = ReleaseReadinessService(
            settings,
            database,
        ).collect(
            expected_cameras=8,
            max_age_hours=24,
            now=now,
        )
        assert result.passed is False
        codes = {
            item.name: item.code
            for item in result.checks
        }
        assert codes == {
            "benchmark": (
                "release_validation_profile_mismatch"
            ),
            "soak": "release_validation_stale",
            "verified_backup": (
                "verified_backup_missing"
            ),
        }
    finally:
        database.close()


def test_release_readiness_rejects_short_8_camera_soak(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    now = datetime(
        2026,
        9,
        21,
        1,
        0,
        tzinfo=UTC,
    )
    try:
        write_report(
            settings,
            kind="benchmark",
            profile="8-camera-baseline",
            passed=True,
            generated_at=(
                now - timedelta(minutes=20)
            ),
        )
        write_report(
            settings,
            kind="soak",
            profile="8-camera-soak",
            passed=True,
            generated_at=(
                now - timedelta(minutes=10)
            ),
            duration_seconds=600,
        )
        add_verified_backup(
            database,
            completed_at=(
                now - timedelta(minutes=5)
            ),
        )

        result = ReleaseReadinessService(
            settings,
            database,
        ).collect(
            expected_cameras=8,
            max_age_hours=24,
            now=now,
        )

        assert result.passed is False
        soak = next(
            item
            for item in result.checks
            if item.name == "soak"
        )
        assert (
            soak.code
            == "release_validation_duration_insufficient"
        )
        assert (
            soak.details["duration_seconds"]
            == 600
        )
        assert (
            soak.details[
                "minimum_duration_seconds"
            ]
            == 3600
        )
    finally:
        database.close()



def test_release_readiness_16_uses_extended_benchmark_only(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    now = datetime(
        2026,
        9,
        21,
        1,
        0,
        tzinfo=UTC,
    )
    try:
        write_report(
            settings,
            kind="benchmark",
            profile="16-camera-extended",
            passed=True,
            generated_at=(
                now - timedelta(minutes=15)
            ),
        )

        result = ReleaseReadinessService(
            settings,
            database,
        ).collect(
            expected_cameras=16,
            max_age_hours=24,
            now=now,
        )

        assert result.passed is True
        assert len(result.checks) == 1
        assert result.checks[0].name == "benchmark"
        assert result.checks[0].code == "ok"
        assert (
            result.checks[0].details[
                "expected_profile"
            ]
            == "16-camera-extended"
        )
    finally:
        database.close()


def test_release_readiness_16_rejects_baseline_profile(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    now = datetime(
        2026,
        9,
        21,
        1,
        0,
        tzinfo=UTC,
    )
    try:
        write_report(
            settings,
            kind="benchmark",
            profile="16-camera-baseline",
            passed=True,
            generated_at=(
                now - timedelta(minutes=15)
            ),
        )

        result = ReleaseReadinessService(
            settings,
            database,
        ).collect(
            expected_cameras=16,
            max_age_hours=24,
            now=now,
        )

        assert result.passed is False
        assert len(result.checks) == 1
        assert (
            result.checks[0].code
            == "release_validation_profile_mismatch"
        )
    finally:
        database.close()
