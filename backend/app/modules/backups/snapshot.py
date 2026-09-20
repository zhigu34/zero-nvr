from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.errors import ApiError


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    backend: str
    path: Path


class DatabaseSnapshotService:
    """Create a database-native consistent snapshot outside ORM transactions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.url = make_url(settings.effective_database_url)

    def create(self, *, destination_dir: Path) -> DatabaseSnapshot:
        destination_dir.mkdir(parents=True, exist_ok=True)
        backend = self.url.get_backend_name()
        if backend == "sqlite":
            return self._sqlite(destination_dir)
        if backend in {"postgresql", "postgres"}:
            return self._postgresql(destination_dir)
        raise ApiError(
            status_code=409,
            code="backup_database_backend_unsupported",
            message="Database backend is not supported for backup.",
        )

    def _sqlite(self, destination_dir: Path) -> DatabaseSnapshot:
        source = self.url.database
        if not source or source == ":memory:":
            raise ApiError(
                status_code=409,
                code="backup_sqlite_source_invalid",
                message="SQLite database path is unavailable for backup.",
            )

        destination = destination_dir / "database.sqlite3"
        source_connection = sqlite3.connect(
            source,
            timeout=self.settings.sqlite_busy_timeout_ms / 1000,
        )
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
            destination_connection.execute("PRAGMA integrity_check")
            destination_connection.commit()
        except sqlite3.Error as exc:
            raise ApiError(
                status_code=503,
                code="backup_database_snapshot_failed",
                message="SQLite online backup failed.",
            ) from exc
        finally:
            destination_connection.close()
            source_connection.close()

        return DatabaseSnapshot(
            backend="sqlite",
            path=destination,
        )

    def _postgresql(self, destination_dir: Path) -> DatabaseSnapshot:
        destination = destination_dir / "database.pgdump"
        env = os.environ.copy()

        password = self.url.password
        if password:
            env["PGPASSWORD"] = password

        args = [
            self.settings.pg_dump_binary,
            "--format=custom",
            "--file",
            str(destination),
            "--no-owner",
            "--no-privileges",
        ]
        if self.url.host:
            args.extend(["--host", self.url.host])
        if self.url.port:
            args.extend(["--port", str(self.url.port)])
        if self.url.username:
            args.extend(["--username", self.url.username])
        if not self.url.database:
            raise ApiError(
                status_code=409,
                code="backup_postgres_database_missing",
                message="PostgreSQL database name is unavailable.",
            )
        args.append(self.url.database)

        try:
            subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
                env=env,
                timeout=self.settings.database_backup_timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise ApiError(
                status_code=503,
                code="pg_dump_unavailable",
                message="pg_dump executable is unavailable.",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ApiError(
                status_code=504,
                code="backup_database_snapshot_timeout",
                message="PostgreSQL database backup timed out.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            # Never surface pg_dump stderr because connection details may leak.
            raise ApiError(
                status_code=503,
                code="backup_database_snapshot_failed",
                message="PostgreSQL database backup failed.",
            ) from exc

        return DatabaseSnapshot(
            backend="postgresql",
            path=destination,
        )


def write_manifest(
    path: Path,
    *,
    app_version: str,
    schema_revision: str,
    database_backend: str,
    backup_set_id: str,
) -> None:
    payload: dict[str, Any] = {
        "format": "zero-nvr-backup-manifest/v1",
        "app_version": app_version,
        "schema_revision": schema_revision,
        "database_backend": database_backend,
        "backup_set_id": backup_set_id,
        "recordings_included": False,
    }
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
