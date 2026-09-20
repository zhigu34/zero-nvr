from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.core.db.types import utc_now
from app.modules.auth.models import User, UserSession
from app.modules.auth.security import PasswordService
from app.modules.backups.execution import (
    BackupExecutionService,
    BackupRunService,
)
from app.modules.backups.models import BackupPolicy
from app.modules.backups.database_snapshot import (
    DatabaseSnapshotService,
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


def safety_snapshot_command(
    _args: argparse.Namespace,
) -> int:
    settings, database = _settings_database()
    try:
        timestamp = datetime.now(UTC).strftime(
            "%Y%m%dT%H%M%SZ"
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
        "%Y%m%dT%H%M%SZ"
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

    safety = sub.add_parser(
        "safety-snapshot"
    )
    safety.set_defaults(
        handler=safety_snapshot_command
    )

    reset = sub.add_parser(
        "admin-reset-password"
    )
    reset.add_argument("--username", required=True)
    reset.add_argument("--password")
    reset.set_defaults(
        handler=reset_password_command
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
