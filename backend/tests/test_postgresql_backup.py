from __future__ import annotations

import subprocess
from pathlib import Path

import app.modules.backups.database_snapshot as snapshot_module
from app.core.config import Settings
from app.core.db import Database
from app.modules.backups.database_snapshot import (
    DatabaseSnapshotService,
)


def test_pg_dump_password_is_environment_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        secret_key="pg-backup-test-secret-key-32-bytes-minimum",
        database_url=(
            "postgresql://backup_user:super-secret-db-password"
            "@db.example:5432/zero_nvr?sslmode=require"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(
            (list(command), dict(kwargs["env"]))
        )
        output = Path(
            command[command.index("--file") + 1]
        )
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        output.write_bytes(b"pgcustom")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(
        snapshot_module.subprocess,
        "run",
        fake_run,
    )
    try:
        result = DatabaseSnapshotService(
            settings
        ).snapshot(
            database,
            destination_dir=tmp_path / "snapshot",
        )
        assert result.engine == "postgresql"
        command, env = calls[0]
        rendered = " ".join(command)
        assert "super-secret-db-password" not in rendered
        assert env["PGPASSWORD"] == "super-secret-db-password"
        assert env["PGSSLMODE"] == "require"
        assert "--format=custom" in command
        assert result.path.read_bytes() == b"pgcustom"
    finally:
        database.close()
