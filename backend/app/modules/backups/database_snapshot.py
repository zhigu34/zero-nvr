from __future__ import annotations

import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.core.db import Database


class DatabaseSnapshotError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    path: Path
    engine: str
    size_bytes: int


class DatabaseSnapshotService:
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self.settings = settings

    @staticmethod
    def _sqlite_source(
        database: Database,
    ) -> Path:
        raw = database.url.database
        if not raw or raw == ":memory:":
            raise DatabaseSnapshotError(
                "backup_sqlite_path_unavailable",
                "SQLite backup requires a file-backed database.",
            )
        return Path(raw).expanduser().resolve()

    def _sqlite(
        self,
        database: Database,
        destination: Path,
    ) -> DatabaseSnapshot:
        source = self._sqlite_source(database)
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination.unlink(missing_ok=True)

        try:
            src = sqlite3.connect(
                str(source),
                timeout=(
                    self.settings.sqlite_busy_timeout_ms
                    / 1000
                ),
            )
            dst = sqlite3.connect(str(destination))
            try:
                src.backup(dst)
                result = dst.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                if (
                    result is None
                    or str(result[0]).lower() != "ok"
                ):
                    raise DatabaseSnapshotError(
                        "backup_sqlite_integrity_failed",
                        "SQLite backup integrity check failed.",
                    )
            finally:
                dst.close()
                src.close()
        except DatabaseSnapshotError:
            destination.unlink(missing_ok=True)
            raise
        except sqlite3.Error as exc:
            destination.unlink(missing_ok=True)
            raise DatabaseSnapshotError(
                "backup_sqlite_failed",
                "SQLite online backup failed.",
            ) from exc

        return DatabaseSnapshot(
            path=destination,
            engine="sqlite",
            size_bytes=destination.stat().st_size,
        )

    def _postgresql(
        self,
        database: Database,
        destination: Path,
    ) -> DatabaseSnapshot:
        url = database.url
        if not url.database:
            raise DatabaseSnapshotError(
                "backup_postgresql_config_invalid",
                "PostgreSQL database name is unavailable.",
            )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination.unlink(missing_ok=True)

        command = [
            self.settings.pg_dump_binary,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(destination),
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
            ["--dbname", url.database]
        )

        env = os.environ.copy()
        if url.password:
            env["PGPASSWORD"] = url.password
        sslmode = url.query.get("sslmode")
        if isinstance(sslmode, str):
            env["PGSSLMODE"] = sslmode

        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=self.settings.database_backup_timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            destination.unlink(missing_ok=True)
            raise DatabaseSnapshotError(
                "backup_postgresql_timeout",
                "PostgreSQL backup timed out.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            destination.unlink(missing_ok=True)
            raise DatabaseSnapshotError(
                "backup_postgresql_failed",
                "PostgreSQL backup failed.",
            ) from exc

        if not destination.is_file():
            raise DatabaseSnapshotError(
                "backup_postgresql_output_missing",
                "PostgreSQL backup output is unavailable.",
            )

        return DatabaseSnapshot(
            path=destination,
            engine="postgresql",
            size_bytes=destination.stat().st_size,
        )

    def snapshot(
        self,
        database: Database,
        *,
        destination_dir: Path,
    ) -> DatabaseSnapshot:
        backend = database.url.get_backend_name()
        if backend == "sqlite":
            return self._sqlite(
                database,
                destination_dir / "database.sqlite3",
            )
        if backend == "postgresql":
            return self._postgresql(
                database,
                destination_dir / "database.pgcustom",
            )
        raise DatabaseSnapshotError(
            "backup_database_backend_unsupported",
            "Database backend is not supported for backup.",
        )
