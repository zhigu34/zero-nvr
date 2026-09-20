from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import app.integrations.restic.adapter as restic_module
from app.integrations.restic import (
    ResticAdapter,
    ResticIntegrationError,
)


REPOSITORY = "s3:s3.amazonaws.com/bucket/zero-nvr"
PASSWORD = "restic-ultra-secret"
AWS_SECRET = "aws-ultra-secret"


def test_restic_secrets_stay_in_environment_not_argv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command, **kwargs):
        env = dict(kwargs["env"])
        calls.append((list(command), env))
        args = command[1:]
        if args[:1] == ["backup"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    '{"message_type":"summary",'
                    '"snapshot_id":"'
                    + "a" * 64
                    + '","data_added":123}\n'
                ),
                stderr="",
            )
        if args[:1] == ["snapshots"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="[]",
                stderr="",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        restic_module.subprocess,
        "run",
        fake_run,
    )

    source = tmp_path / "database.sqlite3"
    source.write_bytes(b"db")
    adapter = ResticAdapter(
        repository=REPOSITORY,
        password=PASSWORD,
        environment={
            "AWS_SECRET_ACCESS_KEY": AWS_SECRET,
        },
    )
    result = adapter.backup(
        paths=[source],
        tags=["zero-nvr"],
    )

    assert result.snapshot_id == "a" * 64
    assert result.size_bytes == 123
    command, env = calls[0]
    rendered = " ".join(command)
    assert REPOSITORY not in rendered
    assert PASSWORD not in rendered
    assert AWS_SECRET not in rendered
    assert env["RESTIC_REPOSITORY"] == REPOSITORY
    assert env["RESTIC_PASSWORD"] == PASSWORD
    assert env["AWS_SECRET_ACCESS_KEY"] == AWS_SECRET


def test_restic_error_never_exposes_stderr_or_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            command,
            stderr=(
                "repository="
                + REPOSITORY
                + " password="
                + PASSWORD
            ),
        )

    monkeypatch.setattr(
        restic_module.subprocess,
        "run",
        fail,
    )
    source = tmp_path / "db.sqlite3"
    source.write_bytes(b"x")

    with pytest.raises(
        ResticIntegrationError
    ) as captured:
        ResticAdapter(
            repository=REPOSITORY,
            password=PASSWORD,
        ).backup(
            paths=[source],
            tags=["zero-nvr"],
        )

    rendered = str(captured.value)
    assert captured.value.code == "restic_operation_failed"
    assert REPOSITORY not in rendered
    assert PASSWORD not in rendered
