from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.integrations.rclone import (
    RcloneAdapter,
    RcloneIntegrationError,
)


SECRET_CONFIG = """[archive]
type = s3
access_key_id = AKIA_TEST
secret_access_key = super-secret-rclone-value
"""


def test_rclone_copy_stat_delete_uses_0600_ephemeral_config(
    tmp_path: Path,
) -> None:
    source = tmp_path / "segment.mp4"
    source.write_bytes(b"x" * 1234)

    calls: list[list[str]] = []
    config_paths: list[Path] = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        config_index = argv.index("--config") + 1
        config_path = Path(argv[config_index])
        config_paths.append(config_path)

        assert config_path.exists()
        assert (config_path.stat().st_mode & 0o777) == 0o600
        assert config_path.read_text() == SECRET_CONFIG
        assert "super-secret-rclone-value" not in " ".join(argv)

        command = argv[1]
        if command == "lsjson":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"Path":"segment.mp4","Size":1234,"IsDir":false}',
                stderr="",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="",
            stderr="",
        )

    adapter = RcloneAdapter(
        config_text=SECRET_CONFIG,
        runner=runner,
    )

    stat = adapter.copy_to_remote(
        source=source,
        destination="archive:zero-nvr/front/segment.mp4",
        expected_size=1234,
    )
    assert stat.size_bytes == 1234

    adapter.delete_file(
        "archive:zero-nvr/front/segment.mp4"
    )

    assert [call[1] for call in calls] == [
        "copyto",
        "lsjson",
        "deletefile",
    ]
    assert "--no-traverse" in calls[0]
    assert "--stat" in calls[1]
    assert all(not path.exists() for path in config_paths)


def test_rclone_error_never_echoes_config_or_stderr_secret(
    tmp_path: Path,
) -> None:
    source = tmp_path / "segment.mp4"
    source.write_bytes(b"x")

    def runner(argv, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            argv,
            output="",
            stderr="backend said super-secret-rclone-value",
        )

    adapter = RcloneAdapter(
        config_text=SECRET_CONFIG,
        runner=runner,
    )

    with pytest.raises(RcloneIntegrationError) as captured:
        adapter.copy_to_remote(
            source=source,
            destination="archive:segment.mp4",
            expected_size=1,
        )

    rendered = str(captured.value)
    assert "super-secret-rclone-value" not in rendered
    assert "AKIA_TEST" not in rendered
    assert captured.value.code == "rclone_operation_failed"


def test_rclone_restore_publishes_atomically(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "restore" / "segment.mp4"

    def runner(argv, **kwargs):
        local_partial = Path(argv[3])
        local_partial.parent.mkdir(parents=True, exist_ok=True)
        local_partial.write_bytes(b"restored")
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="",
            stderr="",
        )

    adapter = RcloneAdapter(
        config_text=SECRET_CONFIG,
        runner=runner,
    )

    result = adapter.copy_to_local(
        source="archive:segment.mp4",
        destination=destination,
        expected_size=len(b"restored"),
    )

    assert result.size_bytes == len(b"restored")
    assert destination.read_bytes() == b"restored"
    assert not destination.with_name(
        destination.name + ".partial"
    ).exists()
