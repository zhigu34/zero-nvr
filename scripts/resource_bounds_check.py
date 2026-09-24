#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT_DIR / "docker-compose.yml"
CORE_SERVICES = (
    "zero-nvr",
    "zero-nvr-worker",
    "zlmediakit",
)


def run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT_DIR,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def parse_size(value: str) -> int:
    match = re.fullmatch(
        r"(?i)(\d+)([kmgt]?)(?:i?b)?",
        value.strip(),
    )
    if match is None:
        raise ValueError(
            f"unsupported size value: {value}"
        )
    amount = int(match.group(1))
    unit = match.group(2).lower()
    multiplier = {
        "": 1,
        "k": 1024,
        "m": 1024**2,
        "g": 1024**3,
        "t": 1024**4,
    }[unit]
    return amount * multiplier


def validate_log_config(
    config: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    if config.get("Type") != "json-file":
        failures.append(
            "log_driver_not_json_file"
        )
        return failures

    options = config.get("Config")
    if not isinstance(options, dict):
        failures.append(
            "log_rotation_options_missing"
        )
        return failures

    raw_size = options.get("max-size")
    raw_files = options.get("max-file")
    try:
        max_size = (
            parse_size(raw_size)
            if isinstance(raw_size, str)
            else 0
        )
    except ValueError:
        max_size = 0
    try:
        max_files = int(raw_files)
    except (TypeError, ValueError):
        max_files = 0

    if max_size <= 0:
        failures.append(
            "log_max_size_invalid"
        )
    if max_files <= 0:
        failures.append(
            "log_max_file_invalid"
        )
    return failures


def parse_volume_size_option(
    options: dict[str, Any],
) -> str | None:
    raw = options.get("o")
    if not isinstance(raw, str):
        return None
    for item in raw.split(","):
        key, sep, value = (
            item.strip().partition("=")
        )
        if sep and key == "size":
            return value
    return None


def compose(
    env_file: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(COMPOSE_FILE),
            *args,
        ]
    )


def container_id(
    env_file: Path,
    service: str,
) -> str:
    value = compose(
        env_file,
        "ps",
        "-q",
        service,
    ).stdout.strip()
    if not value:
        raise RuntimeError(
            f"container unavailable: {service}"
        )
    return value


def inspect_json(
    container: str,
    template: str,
) -> Any:
    raw = run(
        [
            "docker",
            "inspect",
            "--format",
            template,
            container,
        ]
    ).stdout.strip()
    return json.loads(raw)


def prebuffer_mount(
    container: str,
) -> dict[str, Any] | None:
    mounts = inspect_json(
        container,
        "{{json .Mounts}}",
    )
    for mount in mounts:
        if (
            isinstance(mount, dict)
            and mount.get(
                "Destination"
            )
            == "/prebuffer"
        ):
            return mount
    return None


def validate_status(
    status: dict[str, Any],
    *,
    configured_prebuffer_bytes: int,
) -> list[str]:
    failures: list[str] = []
    cache = status.get("playback_cache")
    if not isinstance(cache, dict):
        failures.append(
            "playback_cache_status_missing"
        )
    else:
        usage = cache.get("media_bytes")
        quota = cache.get("max_bytes")
        if (
            not isinstance(usage, int)
            or isinstance(usage, bool)
            or usage < 0
        ):
            failures.append(
                "playback_cache_usage_invalid"
            )
        if (
            not isinstance(quota, int)
            or isinstance(quota, bool)
            or quota <= 0
        ):
            failures.append(
                "playback_cache_quota_invalid"
            )
        if (
            isinstance(usage, int)
            and not isinstance(usage, bool)
            and isinstance(quota, int)
            and not isinstance(quota, bool)
            and usage > quota
        ):
            failures.append(
                "playback_cache_quota_exceeded"
            )
        if cache.get(
            "within_quota"
        ) is not True:
            failures.append(
                "playback_cache_reported_over_quota"
            )

    prebuffer = status.get("prebuffer")
    if not isinstance(prebuffer, dict):
        failures.append(
            "prebuffer_status_missing"
        )
    else:
        if prebuffer.get(
            "require_tmpfs"
        ) is not True:
            failures.append(
                "prebuffer_tmpfs_not_required"
            )
        if prebuffer.get(
            "filesystem_type"
        ) != "tmpfs":
            failures.append(
                "prebuffer_not_tmpfs"
            )
        total = prebuffer.get(
            "total_bytes"
        )
        if (
            not isinstance(total, int)
            or isinstance(total, bool)
            or total <= 0
        ):
            failures.append(
                "prebuffer_total_invalid"
            )
        elif (
            total
            > configured_prebuffer_bytes
            + 4096
        ):
            failures.append(
                "prebuffer_capacity_exceeds_config"
            )
    return failures


def main() -> int:
    env_file = Path(
        os.environ.get(
            "ZERO_NVR_ENV_FILE",
            ROOT_DIR / ".env",
        )
    )
    if not env_file.is_file():
        raise RuntimeError(".env is missing")
    values = read_env_file(env_file)
    configured_size = parse_size(
        values.get(
            "ZERO_NVR_PREBUFFER_SIZE",
            "512m",
        )
    )

    running = [
        item
        for item in compose(
            env_file,
            "ps",
            "--status",
            "running",
            "--services",
        ).stdout.split()
        if item
    ]
    if not running:
        raise RuntimeError(
            "no running Compose services"
        )

    log_results: dict[
        str,
        dict[str, Any],
    ] = {}
    failures: list[str] = []
    container_ids: dict[str, str] = {}
    for service in running:
        cid = container_id(
            env_file,
            service,
        )
        container_ids[service] = cid
        config = inspect_json(
            cid,
            "{{json .HostConfig.LogConfig}}",
        )
        service_failures = (
            validate_log_config(config)
        )
        log_results[service] = {
            "config": config,
            "passed": not service_failures,
            "failures": service_failures,
        }
        failures.extend(
            f"{service}:{item}"
            for item in service_failures
        )

    mounts: dict[
        str,
        dict[str, Any] | None,
    ] = {}
    for service in CORE_SERVICES:
        cid = container_ids.get(service)
        if cid is None:
            failures.append(
                f"{service}:container_not_running"
            )
            mounts[service] = None
            continue
        mounts[service] = prebuffer_mount(
            cid
        )
        if mounts[service] is None:
            failures.append(
                f"{service}:prebuffer_mount_missing"
            )

    volume_name = None
    volume_options: dict[str, Any] = {}
    existing_mounts = [
        mount
        for mount in mounts.values()
        if mount is not None
    ]
    if len(existing_mounts) == len(
        CORE_SERVICES
    ):
        if any(
            mount.get("Type")
            != "volume"
            for mount in existing_mounts
        ):
            failures.append(
                "prebuffer_mount_not_volume"
            )

        names = {
            mount.get("Name")
            for mount in existing_mounts
            if isinstance(
                mount.get("Name"),
                str,
            )
        }
        if len(names) != 1:
            failures.append(
                "prebuffer_volume_not_shared"
            )
        else:
            volume_name = next(
                iter(names)
            )
            volume_options = json.loads(
                run(
                    [
                        "docker",
                        "volume",
                        "inspect",
                        volume_name,
                        "--format",
                        "{{json .Options}}",
                    ]
                ).stdout.strip()
                or "{}"
            )
            if (
                volume_options.get("type")
                != "tmpfs"
                or volume_options.get(
                    "device"
                )
                != "tmpfs"
            ):
                failures.append(
                    "prebuffer_volume_driver_not_tmpfs"
                )
            option_size = (
                parse_volume_size_option(
                    volume_options
                )
            )
            if option_size is None:
                failures.append(
                    "prebuffer_volume_size_missing"
                )
            else:
                try:
                    option_size_bytes = (
                        parse_size(
                            option_size
                        )
                    )
                except ValueError:
                    failures.append(
                        "prebuffer_volume_size_invalid"
                    )
                else:
                    if (
                        option_size_bytes
                        != configured_size
                    ):
                        failures.append(
                            "prebuffer_volume_size_mismatch"
                        )

    status_raw = compose(
        env_file,
        "exec",
        "-T",
        "zero-nvr",
        "python",
        "-m",
        "app.cli",
        "resource-bounds-status",
    ).stdout.strip()
    status = json.loads(
        status_raw
    )
    failures.extend(
        validate_status(
            status,
            configured_prebuffer_bytes=(
                configured_size
            ),
        )
    )

    result = {
        "format": "zero-nvr.resource-bounds",
        "format_version": 1,
        "passed": not failures,
        "docker_logging": {
            "services": log_results,
        },
        "playback_cache": status.get(
            "playback_cache"
        ),
        "prebuffer": {
            **(
                status.get("prebuffer")
                if isinstance(
                    status.get("prebuffer"),
                    dict,
                )
                else {}
            ),
            "configured_bytes": (
                configured_size
            ),
            "volume_name": volume_name,
            "volume_options": (
                volume_options
            ),
        },
        "failures": failures,
    }
    print(
        json.dumps(
            result,
            sort_keys=True,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"error: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
