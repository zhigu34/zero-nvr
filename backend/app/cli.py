from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import shlex
import sqlite3
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import (
    Database,
    assert_database_schema_current,
    database_schema_status,
)
from app.core.db.transfer import DatabaseTransferService
from app.core.db.types import utc_now
from app.modules.auth.models import User, UserSession
from app.modules.auth.security import PasswordService
from app.modules.backups.execution import (
    BackupExecutionService,
    BackupRunService,
)
from app.modules.backups.models import BackupPolicy, BackupSet
from app.modules.backups.service import BackupPolicyService
from app.modules.backups.database_snapshot import (
    DatabaseSnapshotService,
)
from app.modules.system.benchmark import (
    ReleaseBenchmarkService,
)
from app.modules.system.soak import (
    ReleaseSoakService,
)


def _settings_database() -> tuple[Settings, Database]:
    settings = Settings()
    database = Database(settings)
    database.initialize_runtime()
    return settings, database


def _policy(
    database: Database,
    selector: str | None,
) -> BackupPolicy:
    with database.session() as session:
        if selector:
            try:
                policy_id = uuid.UUID(selector)
            except ValueError:
                policy_id = None
            if policy_id is not None:
                policy = session.get(
                    BackupPolicy,
                    policy_id,
                )
            else:
                policy = session.scalar(
                    select(BackupPolicy).where(
                        BackupPolicy.name == selector
                    )
                )
            if policy is None:
                raise RuntimeError(
                    "backup policy was not found"
                )
            return policy

        policies = list(
            session.scalars(
                select(BackupPolicy)
                .where(BackupPolicy.enabled.is_(True))
                .order_by(BackupPolicy.name)
            )
        )
        if not policies:
            raise RuntimeError(
                "no enabled backup policy is configured"
            )
        if len(policies) > 1:
            raise RuntimeError(
                "multiple enabled backup policies exist; pass --policy"
            )
        return policies[0]


def check_schema_command(
    _args: argparse.Namespace,
) -> int:
    _settings, database = _settings_database()
    try:
        status = database_schema_status(
            database
        )
        assert_database_schema_current(
            database
        )
        print(
            json.dumps(
                {
                    "compatible": True,
                    "current": sorted(
                        status.current
                    ),
                    "expected": sorted(
                        status.expected
                    ),
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        database.close()


def _alembic_upgrade_database_url(
    database_url: str,
) -> None:
    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )
    config = Config(
        str(root / "alembic.ini")
    )
    config.set_main_option(
        "script_location",
        str(root / "alembic"),
    )

    previous = os.environ.get(
        "ZERO_NVR_DATABASE_URL"
    )
    os.environ[
        "ZERO_NVR_DATABASE_URL"
    ] = database_url
    try:
        command.upgrade(
            config,
            "head",
        )
    finally:
        if previous is None:
            os.environ.pop(
                "ZERO_NVR_DATABASE_URL",
                None,
            )
        else:
            os.environ[
                "ZERO_NVR_DATABASE_URL"
            ] = previous


def database_transfer_command(
    args: argparse.Namespace,
) -> int:
    target_env = (
        args.target_url_env.strip()
    )
    if not target_env:
        raise RuntimeError(
            "target database URL environment variable name is required"
        )

    target_url = (
        os.environ.get(target_env) or ""
    ).strip()
    if not target_url:
        raise RuntimeError(
            f"target database URL environment variable is empty: {target_env}"
        )

    settings, source = _settings_database()
    target_settings = settings.model_copy(
        update={
            "database_url": target_url,
        }
    )
    target = Database(target_settings)

    try:
        source_backend = (
            source.url.get_backend_name()
        )
        target_backend = (
            target.url.get_backend_name()
        )
        source_backend = (
            "postgresql"
            if source_backend
            in {"postgres", "postgresql"}
            else source_backend
        )
        target_backend = (
            "postgresql"
            if target_backend
            in {"postgres", "postgresql"}
            else target_backend
        )

        if (
            source_backend
            == target_backend
            and not args.allow_same_backend
        ):
            raise RuntimeError(
                "database transfer target backend must differ from the active backend"
            )

        source.ping()
        _alembic_upgrade_database_url(
            target_url
        )
        target.initialize_runtime()
        target.ping()

        result = DatabaseTransferService(
            batch_size=args.batch_size
        ).transfer(
            source=source,
            target=target,
        )
        print(
            json.dumps(
                {
                    "transferred": True,
                    "source_backend": (
                        result.source_backend
                    ),
                    "target_backend": (
                        result.target_backend
                    ),
                    "total_rows": (
                        result.total_rows
                    ),
                    "table_counts": (
                        result.table_counts
                    ),
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        target.close()
        source.close()


def recovery_env_command(
    args: argparse.Namespace,
) -> int:
    settings, database = _settings_database()
    try:
        policy = _policy(database, args.policy)
        with database.session() as session:
            attached = session.get(
                BackupPolicy,
                policy.id,
            )
            assert attached is not None
            resolved = BackupPolicyService(
                settings
            ).resolve(
                session,
                policy=attached,
            )
            session.commit()

        values = {
            "RESTIC_REPOSITORY": (
                resolved.repository
            ),
            "RESTIC_PASSWORD": (
                resolved.password
            ),
            **resolved.environment,
        }
        print(
            "# zero-nvr RecoveryKit restic bootstrap"
        )
        print(
            "# Generated from encrypted BackupPolicy secrets."
        )
        for key in sorted(values):
            print(
                f"{key}={shlex.quote(values[key])}"
            )
        return 0
    finally:
        database.close()


def backup_command(args: argparse.Namespace) -> int:
    settings, database = _settings_database()
    try:
        policy = _policy(database, args.policy)
        with database.session() as session:
            attached = session.get(
                BackupPolicy,
                policy.id,
            )
            assert attached is not None
            backup_set, _created = BackupRunService.reserve(
                session,
                policy=attached,
                settings=settings,
                database=database,
                reason=args.reason,
            )
            backup_id = backup_set.id
            session.commit()

        state = BackupExecutionService(
            settings
        ).execute(
            database,
            backup_set_id=backup_id,
        )
        print(
            json.dumps(
                {
                    "backup_id": str(backup_id),
                    "state": state,
                },
                sort_keys=True,
            )
        )
        return 0 if state == "COMPLETED" else 1
    finally:
        database.close()


def _pre_upgrade_policy(
    database: Database,
    selector: str | None,
) -> BackupPolicy:
    if selector:
        policy = _policy(
            database,
            selector,
        )
        with database.session() as session:
            attached = session.get(
                BackupPolicy,
                policy.id,
            )
            if attached is None:
                raise RuntimeError(
                    "backup policy was not found"
                )
            if not attached.enabled:
                raise RuntimeError(
                    "pre-upgrade backup policy must be enabled"
                )
            if not attached.verify_after_backup:
                raise RuntimeError(
                    "pre-upgrade backup policy must enable verify_after_backup"
                )
            if (
                attached.database_backend
                != database.url.get_backend_name()
            ):
                raise RuntimeError(
                    "pre-upgrade backup policy database backend does not match the active database"
                )
            return attached

    with database.session() as session:
        candidates = list(
            session.scalars(
                select(BackupPolicy)
                .where(
                    BackupPolicy.enabled.is_(True),
                    BackupPolicy.verify_after_backup.is_(True),
                    BackupPolicy.database_backend
                    == database.url.get_backend_name(),
                )
                .order_by(BackupPolicy.name)
            )
        )
        if not candidates:
            raise RuntimeError(
                "no enabled verified backup policy is configured; create one before updating"
            )
        if len(candidates) > 1:
            names = ", ".join(
                item.name
                for item in candidates
            )
            raise RuntimeError(
                "multiple verified backup policies are enabled; pass --policy with an id or name "
                f"({names})"
            )
        return candidates[0]


def _verified_safety_backup_command(
    args: argparse.Namespace,
    *,
    reason: str,
    operation: str,
) -> int:
    settings, database = _settings_database()
    try:
        policy = _pre_upgrade_policy(
            database,
            args.policy,
        )
        policy_id = policy.id
        with database.session() as session:
            attached = session.get(
                BackupPolicy,
                policy_id,
            )
            assert attached is not None
            backup_set, _created = (
                BackupRunService.reserve(
                    session,
                    policy=attached,
                    settings=settings,
                    database=database,
                    reason=reason,
                )
            )
            backup_id = backup_set.id
            session.commit()

        state = BackupExecutionService(
            settings
        ).execute(
            database,
            backup_set_id=backup_id,
        )

        with database.session() as session:
            completed = session.get(
                BackupSet,
                backup_id,
            )
            if completed is None:
                raise RuntimeError(
                    f"{operation} backup record disappeared"
                )

            payload = {
                "backup_id": str(backup_id),
                "policy_id": str(policy_id),
                "state": completed.state,
                "verification_state": (
                    completed.verification_state
                ),
                "restic_snapshot_id": (
                    completed.restic_snapshot_id
                ),
                "reason": reason,
            }

            if (
                state != "COMPLETED"
                or completed.state != "COMPLETED"
                or completed.verification_state
                != "PASSED"
                or not completed.restic_snapshot_id
            ):
                print(
                    json.dumps(
                        payload,
                        sort_keys=True,
                    )
                )
                raise RuntimeError(
                    f"{operation} backup did not complete with verified restic snapshot"
                )

            print(
                json.dumps(
                    payload,
                    sort_keys=True,
                )
            )
        return 0
    finally:
        database.close()


def pre_upgrade_backup_command(
    args: argparse.Namespace,
) -> int:
    return _verified_safety_backup_command(
        args,
        reason="pre_upgrade",
        operation="pre-upgrade",
    )


def pre_database_migration_backup_command(
    args: argparse.Namespace,
) -> int:
    return _verified_safety_backup_command(
        args,
        reason="pre_database_migration",
        operation="pre-database-migration",
    )

def safety_snapshot_command(
    _args: argparse.Namespace,
) -> int:
    settings, database = _settings_database()
    try:
        timestamp = datetime.now(UTC).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        destination = (
            settings.data_dir
            / "safety-backups"
            / timestamp
        )
        snapshot = DatabaseSnapshotService(
            settings
        ).snapshot(
            database,
            destination_dir=destination,
        )
        print(
            json.dumps(
                {
                    "safety_snapshot": str(
                        snapshot.path
                    ),
                    "database_engine": (
                        snapshot.engine
                    ),
                    "size_bytes": (
                        snapshot.size_bytes
                    ),
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        database.close()





def benchmark_status_command(
    args: argparse.Namespace,
) -> int:
    settings, database = _settings_database()
    try:
        status = ReleaseBenchmarkService(
            settings,
            database,
        ).collect(
            expected_cameras=args.expected_cameras,
        )
        print(
            json.dumps(
                {
                    "expected_cameras": (
                        status.expected_cameras
                    ),
                    "enabled_cameras": (
                        status.enabled_cameras
                    ),
                    "recording_expected_cameras": (
                        status.recording_expected_cameras
                    ),
                    "record_streams_online": (
                        status.record_streams_online
                    ),
                    "recorders_active": (
                        status.recorders_active
                    ),
                    "passed": status.passed,
                    "failures": list(
                        status.failures
                    ),
                    "cameras": [
                        {
                            "camera_id": str(
                                item.camera_id
                            ),
                            "name": item.name,
                            "desired_mode": (
                                item.desired_mode
                            ),
                            "stream_online": (
                                item.stream_online
                            ),
                            "recording_active": (
                                item.recording_active
                            ),
                            "error": item.error,
                        }
                        for item in status.cameras
                    ],
                },
                sort_keys=True,
            )
        )
        return 0 if status.passed else 1
    finally:
        database.close()





def _parse_aware_datetime(
    value: str,
    *,
    field: str,
) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = (
            normalized[:-1] + "+00:00"
        )
    try:
        parsed = datetime.fromisoformat(
            normalized
        )
    except ValueError as exc:
        raise RuntimeError(
            f"{field} must be an ISO 8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise RuntimeError(
            f"{field} must include a timezone"
        )
    return parsed.astimezone(UTC)


def soak_status_command(
    args: argparse.Namespace,
) -> int:
    settings, database = _settings_database()
    try:
        status = ReleaseSoakService(
            settings,
            database,
        ).collect(
            expected_cameras=(
                args.expected_cameras
            ),
            since=_parse_aware_datetime(
                args.since,
                field="since",
            ),
            require_progress=(
                args.require_progress
            ),
        )
        print(
            json.dumps(
                {
                    "expected_cameras": (
                        status.expected_cameras
                    ),
                    "sampled_at": (
                        status.sampled_at
                        .isoformat()
                    ),
                    "since": (
                        status.since.isoformat()
                    ),
                    "passed": status.passed,
                    "failures": list(
                        status.failures
                    ),
                    "required_health": (
                        status.required_health
                    ),
                    "runtime": {
                        "passed": (
                            status.runtime.passed
                        ),
                        "enabled_cameras": (
                            status.runtime
                            .enabled_cameras
                        ),
                        "recording_expected_cameras": (
                            status.runtime
                            .recording_expected_cameras
                        ),
                        "record_streams_online": (
                            status.runtime
                            .record_streams_online
                        ),
                        "recorders_active": (
                            status.runtime
                            .recorders_active
                        ),
                        "failures": list(
                            status.runtime
                            .failures
                        ),
                    },
                    "progress_required": (
                        status.progress_required
                    ),
                    "persistent_progress": [
                        {
                            "camera_id": str(
                                item.camera_id
                            ),
                            "name": item.name,
                            "segment_target_seconds": (
                                item.segment_target_seconds
                            ),
                            "segments_since_start": (
                                item.segments_since_start
                            ),
                            "available_local_segments_since_start": (
                                item.available_local_segments_since_start
                            ),
                            "bytes_since_start": (
                                item.bytes_since_start
                            ),
                            "latest_segment_created_at": (
                                item.latest_segment_created_at
                                .isoformat()
                                if item.latest_segment_created_at
                                is not None
                                else None
                            ),
                            "passed": item.passed,
                        }
                        for item
                        in status.persistent_progress
                    ],
                },
                sort_keys=True,
            )
        )
        return 0 if status.passed else 1
    finally:
        database.close()


def reset_password_command(
    args: argparse.Namespace,
) -> int:
    settings, database = _settings_database()
    try:
        password = args.password
        if password is None:
            password = getpass.getpass(
                "New password: "
            )
            confirm = getpass.getpass(
                "Confirm password: "
            )
            if password != confirm:
                raise RuntimeError(
                    "password confirmation does not match"
                )
        if len(password) < 12 or len(password) > 1024:
            raise RuntimeError(
                "password must be between 12 and 1024 characters"
            )

        passwords = PasswordService()
        with database.session() as session:
            user = session.scalar(
                select(User).where(
                    User.username == args.username
                )
            )
            if user is None:
                raise RuntimeError("user was not found")
            user.password_hash = passwords.hash(password)
            user.enabled = True
            now = utc_now()
            for item in session.scalars(
                select(UserSession).where(
                    UserSession.user_id == user.id,
                    UserSession.revoked_at.is_(None),
                )
            ):
                item.revoked_at = now
            session.commit()

        print(
            json.dumps(
                {
                    "username": args.username,
                    "password_reset": True,
                    "sessions_revoked": True,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        database.close()


def _find_manifest(root: Path) -> tuple[Path, dict[str, object]]:
    candidates: list[
        tuple[Path, dict[str, object]]
    ] = []
    for path in root.rglob("manifest.json"):
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            continue
        if (
            isinstance(payload, dict)
            and isinstance(
                payload.get("backup_set_id"),
                str,
            )
            and payload.get("recordings_included")
            is False
            and isinstance(
                payload.get("database_snapshot"),
                str,
            )
        ):
            candidates.append((path, payload))

    if len(candidates) != 1:
        raise RuntimeError(
            "restore staging must contain exactly one zero-nvr backup manifest"
        )
    return candidates[0]


def _known_revisions() -> set[str]:
    config = Config(
        str(
            Path(__file__)
            .resolve()
            .parents[1]
            / "alembic.ini"
        )
    )
    script = ScriptDirectory.from_config(config)
    return {
        revision.revision
        for revision in script.walk_revisions()
    }


def _validate_restore_manifest(
    *,
    settings: Settings,
    database: Database,
    root: Path,
) -> tuple[Path, dict[str, object], Path]:
    manifest_path, manifest = _find_manifest(root)
    engine = str(
        manifest.get("database_engine")
        or manifest.get("database_backend")
        or ""
    )
    active = database.url.get_backend_name()
    active = (
        "postgresql"
        if active in {"postgres", "postgresql"}
        else active
    )
    if engine != active:
        raise RuntimeError(
            "backup database engine does not match this deployment"
        )

    revision = str(
        manifest.get("schema_revision") or ""
    )
    if (
        revision
        and revision not in {"unknown", "unversioned"}
        and revision not in _known_revisions()
    ):
        raise RuntimeError(
            "backup schema revision is newer or unknown to this zero-nvr version"
        )

    snapshot_name = str(
        manifest["database_snapshot"]
    )
    if (
        Path(snapshot_name).name != snapshot_name
        or snapshot_name in {".", ".."}
    ):
        raise RuntimeError(
            "backup manifest database snapshot path is invalid"
        )
    snapshot = (
        manifest_path.parent / snapshot_name
    ).resolve()
    if not snapshot.is_file():
        raise RuntimeError(
            "backup database snapshot is missing"
        )
    return manifest_path, manifest, snapshot


def _verify_sqlite(path: Path) -> None:
    connection = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
    )
    try:
        row = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()
    finally:
        connection.close()
    if row is None or str(row[0]).lower() != "ok":
        raise RuntimeError(
            "restored SQLite snapshot failed integrity_check"
        )


def _postgres_restore(
    *,
    settings: Settings,
    database: Database,
    snapshot: Path,
) -> None:
    url = database.url
    if not url.database:
        raise RuntimeError(
            "PostgreSQL database name is unavailable"
        )

    command = [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
    ]
    if url.host:
        command.extend(["--host", url.host])
    if url.port:
        command.extend(
            ["--port", str(url.port)]
        )
    if url.username:
        command.extend(
            ["--username", url.username]
        )
    command.extend(
        ["--dbname", url.database, str(snapshot)]
    )

    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    sslmode = url.query.get("sslmode")
    if isinstance(sslmode, str):
        env["PGSSLMODE"] = sslmode

    subprocess.run(
        command,
        check=True,
        capture_output=True,
        timeout=settings.database_backup_timeout_seconds,
        env=env,
    )


def _normalize_database_backend(
    database: Database,
) -> str:
    backend = database.url.get_backend_name()
    return (
        "postgresql"
        if backend in {"postgres", "postgresql"}
        else backend
    )


def _validated_safety_snapshot(
    *,
    settings: Settings,
    database: Database,
    raw_path: str,
) -> Path:
    root = (
        settings.data_dir
        / "safety-backups"
    ).resolve()
    snapshot = Path(raw_path).resolve()
    try:
        snapshot.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(
            "safety snapshot must be inside the zero-nvr safety-backups directory"
        ) from exc

    if not snapshot.is_file():
        raise RuntimeError(
            "safety snapshot is unavailable"
        )

    backend = _normalize_database_backend(
        database
    )
    expected = {
        "sqlite": "database.sqlite3",
        "postgresql": "database.pgcustom",
    }.get(backend)
    if expected is None:
        raise RuntimeError(
            "database backend is not supported for safety rollback"
        )
    if snapshot.name != expected:
        raise RuntimeError(
            "safety snapshot does not match the active database backend"
        )
    return snapshot


def _restore_safety_snapshot(
    *,
    settings: Settings,
    database: Database,
    snapshot: Path,
) -> tuple[str, Path | None]:
    backend = _normalize_database_backend(
        database
    )
    timestamp = datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    rollback_dir = (
        settings.data_dir
        / "restore-rollback"
        / timestamp
    )
    rollback_dir.mkdir(
        parents=True,
        exist_ok=False,
    )
    rollback_snapshot: Path | None = None

    if backend == "sqlite":
        target_raw = database.url.database
        if not target_raw:
            raise RuntimeError(
                "SQLite target path is unavailable"
            )
        target = Path(target_raw).resolve()
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if target.exists():
            current = DatabaseSnapshotService(
                settings
            ).snapshot(
                database,
                destination_dir=rollback_dir,
            )
            rollback_snapshot = current.path

        _verify_sqlite(snapshot)
        database.close()

        partial = target.with_name(
            target.name + ".rollback.partial"
        )
        partial.unlink(missing_ok=True)
        shutil.copy2(snapshot, partial)
        try:
            _verify_sqlite(partial)
            with partial.open("rb+") as handle:
                os.fsync(handle.fileno())
            for suffix in ("-wal", "-shm"):
                sidecar = Path(
                    str(target) + suffix
                )
                if sidecar.exists():
                    shutil.move(
                        sidecar,
                        rollback_dir
                        / sidecar.name,
                    )
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)

    elif backend == "postgresql":
        current = DatabaseSnapshotService(
            settings
        ).snapshot(
            database,
            destination_dir=rollback_dir,
        )
        rollback_snapshot = current.path
        try:
            _postgres_restore(
                settings=settings,
                database=database,
                snapshot=snapshot,
            )
        except Exception:
            _postgres_restore(
                settings=settings,
                database=database,
                snapshot=current.path,
            )
            raise
        finally:
            database.close()
    else:
        raise RuntimeError(
            "database backend is not supported for safety rollback"
        )

    return backend, rollback_snapshot


def restore_safety_snapshot_command(
    args: argparse.Namespace,
) -> int:
    if not args.force:
        raise RuntimeError(
            "restore-safety-snapshot requires --force"
        )

    settings, database = _settings_database()
    try:
        snapshot = _validated_safety_snapshot(
            settings=settings,
            database=database,
            raw_path=args.path,
        )
        backend, rollback_snapshot = (
            _restore_safety_snapshot(
                settings=settings,
                database=database,
                snapshot=snapshot,
            )
        )
        print(
            json.dumps(
                {
                    "restored": True,
                    "safety_snapshot": str(
                        snapshot
                    ),
                    "database_engine": backend,
                    "rollback_snapshot": (
                        str(rollback_snapshot)
                        if rollback_snapshot
                        is not None
                        else None
                    ),
                    "recordings_modified": False,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        database.close()


def restore_staged_command(
    args: argparse.Namespace,
) -> int:
    if not args.force:
        raise RuntimeError(
            "restore-staged requires --force"
        )

    settings = Settings()
    database = Database(settings)
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise RuntimeError(
            "restore staging directory is unavailable"
        )

    _manifest_path, manifest, snapshot = (
        _validate_restore_manifest(
            settings=settings,
            database=database,
            root=root,
        )
    )

    timestamp = datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    rollback_dir = (
        settings.data_dir
        / "restore-rollback"
        / timestamp
    )
    rollback_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    backend = database.url.get_backend_name()
    backend = (
        "postgresql"
        if backend in {"postgres", "postgresql"}
        else backend
    )

    rollback_snapshot: Path | None = None
    try:
        if backend == "sqlite":
            target_raw = database.url.database
            if not target_raw:
                raise RuntimeError(
                    "SQLite target path is unavailable"
                )
            target = Path(target_raw).resolve()
            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if target.exists():
                safety = DatabaseSnapshotService(
                    settings
                ).snapshot(
                    database,
                    destination_dir=rollback_dir,
                )
                rollback_snapshot = safety.path

            _verify_sqlite(snapshot)
            database.close()

            partial = target.with_name(
                target.name + ".restore.partial"
            )
            shutil.copy2(snapshot, partial)
            _verify_sqlite(partial)
            with partial.open("rb+") as handle:
                os.fsync(handle.fileno())
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(target) + suffix)
                if sidecar.exists():
                    shutil.move(
                        sidecar,
                        rollback_dir
                        / sidecar.name,
                    )
            os.replace(partial, target)

        elif backend == "postgresql":
            safety = DatabaseSnapshotService(
                settings
            ).snapshot(
                database,
                destination_dir=rollback_dir,
            )
            rollback_snapshot = safety.path
            try:
                _postgres_restore(
                    settings=settings,
                    database=database,
                    snapshot=snapshot,
                )
            except Exception:
                _postgres_restore(
                    settings=settings,
                    database=database,
                    snapshot=safety.path,
                )
                raise
            finally:
                database.close()
        else:
            raise RuntimeError(
                "database backend is not supported for restore"
            )

        print(
            json.dumps(
                {
                    "restored": True,
                    "backup_set_id": manifest.get(
                        "backup_set_id"
                    ),
                    "database_engine": backend,
                    "rollback_snapshot": (
                        str(rollback_snapshot)
                        if rollback_snapshot is not None
                        else None
                    ),
                    "recordings_modified": False,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli"
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    schema = sub.add_parser(
        "check-schema"
    )
    schema.set_defaults(
        handler=check_schema_command
    )

    transfer = sub.add_parser(
        "database-transfer"
    )
    transfer.add_argument(
        "--target-url-env",
        default=(
            "ZERO_NVR_DATABASE_MIGRATION_TARGET_URL"
        ),
    )
    transfer.add_argument(
        "--batch-size",
        type=int,
        default=500,
    )
    transfer.add_argument(
        "--allow-same-backend",
        action="store_true",
    )
    transfer.set_defaults(
        handler=database_transfer_command
    )

    recovery = sub.add_parser(
        "recovery-env"
    )
    recovery.add_argument("--policy")
    recovery.set_defaults(
        handler=recovery_env_command
    )

    backup = sub.add_parser("backup")
    backup.add_argument("--policy")
    backup.add_argument(
        "--reason",
        default="manual",
        choices=[
            "manual",
            "pre_upgrade",
            "pre_restore",
            "pre_database_migration",
        ],
    )
    backup.set_defaults(handler=backup_command)

    pre_upgrade = sub.add_parser(
        "pre-upgrade-backup"
    )
    pre_upgrade.add_argument("--policy")
    pre_upgrade.set_defaults(
        handler=pre_upgrade_backup_command
    )

    pre_database_migration = sub.add_parser(
        "pre-database-migration-backup"
    )
    pre_database_migration.add_argument(
        "--policy"
    )
    pre_database_migration.set_defaults(
        handler=pre_database_migration_backup_command
    )

    safety = sub.add_parser(
        "safety-snapshot"
    )
    safety.set_defaults(
        handler=safety_snapshot_command
    )

    benchmark = sub.add_parser(
        "benchmark-status"
    )
    benchmark.add_argument(
        "--expected-cameras",
        type=int,
        required=True,
    )
    benchmark.set_defaults(
        handler=benchmark_status_command
    )

    soak = sub.add_parser(
        "soak-status"
    )
    soak.add_argument(
        "--expected-cameras",
        type=int,
        required=True,
    )
    soak.add_argument(
        "--since",
        required=True,
    )
    soak.add_argument(
        "--require-progress",
        action="store_true",
    )
    soak.set_defaults(
        handler=soak_status_command
    )

    reset = sub.add_parser(
        "admin-reset-password"
    )
    reset.add_argument("--username", required=True)
    reset.add_argument("--password")
    reset.set_defaults(
        handler=reset_password_command
    )

    safety_restore = sub.add_parser(
        "restore-safety-snapshot"
    )
    safety_restore.add_argument(
        "--path",
        required=True,
    )
    safety_restore.add_argument(
        "--force",
        action="store_true",
    )
    safety_restore.set_defaults(
        handler=restore_safety_snapshot_command
    )

    restore = sub.add_parser("restore-staged")
    restore.add_argument("--root", required=True)
    restore.add_argument(
        "--force",
        action="store_true",
    )
    restore.set_defaults(
        handler=restore_staged_command
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except Exception as exc:
        print(
            f"error: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
