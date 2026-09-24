from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parent
    / "resource_bounds_check.py"
)
SPEC = importlib.util.spec_from_file_location(
    "resource_bounds_check",
    MODULE_PATH,
)
assert SPEC is not None
assert SPEC.loader is not None
module = importlib.util.module_from_spec(
    SPEC
)
SPEC.loader.exec_module(module)


def test_parse_size() -> None:
    assert module.parse_size(
        "512m"
    ) == 512 * 1024**2
    assert module.parse_size(
        "10MB"
    ) == 10 * 1024**2
    assert module.parse_size(
        "1GiB"
    ) == 1024**3


def test_log_config_requires_rotation() -> None:
    assert module.validate_log_config(
        {
            "Type": "json-file",
            "Config": {
                "max-size": "10m",
                "max-file": "3",
            },
        }
    ) == []
    assert (
        "log_max_file_invalid"
        in module.validate_log_config(
            {
                "Type": "json-file",
                "Config": {
                    "max-size": "10m",
                    "max-file": "0",
                },
            }
        )
    )


def test_backend_status_bounds() -> None:
    status = {
        "playback_cache": {
            "media_bytes": 1024,
            "max_bytes": 4096,
            "within_quota": True,
        },
        "prebuffer": {
            "require_tmpfs": True,
            "filesystem_type": "tmpfs",
            "total_bytes": 512 * 1024**2,
        },
    }
    assert module.validate_status(
        status,
        configured_prebuffer_bytes=(
            512 * 1024**2
        ),
    ) == []

    status["playback_cache"][
        "media_bytes"
    ] = 8192
    failures = module.validate_status(
        status,
        configured_prebuffer_bytes=(
            512 * 1024**2
        ),
    )
    assert (
        "playback_cache_quota_exceeded"
        in failures
    )


def test_volume_size_option() -> None:
    assert (
        module.parse_volume_size_option(
            {
                "o": (
                    "size=512m,"
                    "mode=1770"
                ),
            }
        )
        == "512m"
    )


if __name__ == "__main__":
    test_parse_size()
    test_log_config_requires_rotation()
    test_backend_status_bounds()
    test_volume_size_option()
    print(
        "resource bounds validation: ok"
    )
