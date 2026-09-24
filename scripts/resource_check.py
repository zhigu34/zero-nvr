#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT_DIR / "docker-compose.yml"
STATIC_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
IDLE_MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
IDLE_MIN_SETTLE_SECONDS = 60
IDLE_MIN_SAMPLES = 5
CORE_SERVICES = (
    "zero-nvr",
    "zero-nvr-worker",
    "zlmediakit",
)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            "must be a positive integer"
        )
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Validate persisted Plan 04 resource evidence"
        )
    )
    result.add_argument(
        "check",
        choices=("static", "idle"),
    )
    result.add_argument(
        "--max-age-hours",
        type=positive_int,
        default=168,
    )
    return result


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


def host_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def parse_generated_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def integer(
    value: object,
) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def validate_static(
    report: dict[str, Any],
    *,
    current_images: dict[str, str],
    max_age_hours: int,
    now: datetime,
) -> dict[str, Any]:
    failures: list[str] = []

    if (
        report.get("format")
        != "zero-nvr.resource-baseline"
    ):
        failures.append("format_mismatch")
    if report.get("format_version") != 1:
        failures.append("format_version_mismatch")
    if report.get("profile") != "r1-clean-core-idle":
        failures.append("profile_mismatch")

    generated_at = parse_generated_at(
        report.get("generated_at")
    )
    age_seconds: int | None = None
    if generated_at is None:
        failures.append("generated_at_invalid")
    else:
        age = now.astimezone(UTC) - generated_at
        age_seconds = max(
            0,
            int(age.total_seconds()),
        )
        if (
            generated_at > now.astimezone(UTC)
            + timedelta(minutes=5)
        ):
            failures.append(
                "generated_at_in_future"
            )
        elif age > timedelta(
            hours=max_age_hours
        ):
            failures.append("evidence_stale")

    clean = report.get("clean_core")
    if not isinstance(clean, dict):
        failures.append("clean_core_missing")
        clean = {}
    if clean.get("configured_cameras") != 0:
        failures.append(
            "configured_cameras_not_zero"
        )
    if clean.get("enabled_cameras") != 0:
        failures.append(
            "enabled_cameras_not_zero"
        )
    if clean.get(
        "optional_compose_profiles"
    ) != []:
        failures.append(
            "optional_profiles_enabled"
        )

    static = report.get("static_footprint")
    if not isinstance(static, dict):
        failures.append(
            "static_footprint_missing"
        )
        static = {}

    total = integer(
        static.get("total_bytes")
    )
    image = integer(
        static.get(
            "image_virtual_bytes_conservative"
        )
    )
    writable = integer(
        static.get(
            "container_writable_bytes"
        )
    )
    initial = integer(
        static.get(
            "initial_product_state_bytes"
        )
    )
    logs = integer(
        static.get(
            "current_log_stream_bytes"
        )
    )

    components = (
        image,
        writable,
        initial,
        logs,
    )
    if any(
        value is None or value < 0
        for value in components
    ):
        failures.append(
            "static_components_invalid"
        )
        recomputed = None
    else:
        recomputed = sum(
            value
            for value in components
            if value is not None
        )

    if total is None or total < 0:
        failures.append(
            "static_total_invalid"
        )
    elif recomputed is not None and total != recomputed:
        failures.append(
            "static_total_mismatch"
        )

    if total is not None and total >= STATIC_LIMIT_BYTES:
        failures.append(
            "static_footprint_limit_exceeded"
        )
    if static.get("passed") is not True:
        failures.append(
            "reported_static_gate_failed"
        )

    initial_parts = (
        integer(static.get("data_bytes")),
        integer(static.get("env_bytes")),
        integer(
            static.get(
                "generated_zlm_config_bytes"
            )
        ),
    )
    if any(
        value is None or value < 0
        for value in initial_parts
    ):
        failures.append(
            "initial_state_components_invalid"
        )
    elif (
        initial is not None
        and initial
        != sum(
            value
            for value in initial_parts
            if value is not None
        )
    ):
        failures.append(
            "initial_state_total_mismatch"
        )

    containers = report.get("containers")
    recorded_images: dict[str, str] = {}
    if isinstance(containers, list):
        for item in containers:
            if not isinstance(item, dict):
                continue
            service = item.get("service")
            image_id = item.get("image_id")
            if (
                isinstance(service, str)
                and service in CORE_SERVICES
                and isinstance(image_id, str)
            ):
                recorded_images[
                    service
                ] = image_id

    if set(recorded_images) != set(
        CORE_SERVICES
    ):
        failures.append(
            "recorded_core_images_incomplete"
        )
    if set(current_images) != set(
        CORE_SERVICES
    ):
        failures.append(
            "current_core_images_incomplete"
        )
    elif recorded_images != current_images:
        failures.append(
            "core_image_identity_changed"
        )

    return {
        "check": "static",
        "passed": not failures,
        "generated_at": (
            generated_at.isoformat()
            if generated_at is not None
            else None
        ),
        "age_seconds": age_seconds,
        "max_age_hours": max_age_hours,
        "total_bytes": total,
        "limit_bytes": STATIC_LIMIT_BYTES,
        "headroom_bytes": (
            STATIC_LIMIT_BYTES - total
            if total is not None
            else None
        ),
        "recorded_images": recorded_images,
        "current_images": current_images,
        "failures": failures,
    }


def validate_idle(
    report: dict[str, Any],
    *,
    current_images: dict[str, str],
    max_age_hours: int,
    now: datetime,
) -> dict[str, Any]:
    failures: list[str] = []

    if (
        report.get("format")
        != "zero-nvr.resource-baseline"
    ):
        failures.append("format_mismatch")
    if report.get("format_version") != 1:
        failures.append("format_version_mismatch")
    if report.get("profile") != "r1-clean-core-idle":
        failures.append("profile_mismatch")

    generated_at = parse_generated_at(
        report.get("generated_at")
    )
    age_seconds: int | None = None
    if generated_at is None:
        failures.append("generated_at_invalid")
    else:
        age = now.astimezone(UTC) - generated_at
        age_seconds = max(
            0,
            int(age.total_seconds()),
        )
        if (
            generated_at
            > now.astimezone(UTC)
            + timedelta(minutes=5)
        ):
            failures.append(
                "generated_at_in_future"
            )
        elif age > timedelta(
            hours=max_age_hours
        ):
            failures.append("evidence_stale")

    clean = report.get("clean_core")
    if not isinstance(clean, dict):
        failures.append("clean_core_missing")
        clean = {}
    if clean.get("configured_cameras") != 0:
        failures.append(
            "configured_cameras_not_zero"
        )
    if clean.get("enabled_cameras") != 0:
        failures.append(
            "enabled_cameras_not_zero"
        )
    if clean.get(
        "optional_compose_profiles"
    ) != []:
        failures.append(
            "optional_profiles_enabled"
        )

    idle = report.get("idle_runtime")
    if not isinstance(idle, dict):
        failures.append("idle_runtime_missing")
        idle = {}

    peak = integer(
        idle.get("core_memory_peak_bytes")
    )
    average = integer(
        idle.get("core_memory_avg_bytes")
    )
    reported_limit = integer(
        idle.get("core_memory_limit_bytes")
    )
    settle = integer(
        idle.get("settle_seconds")
    )
    samples = integer(
        idle.get("samples")
    )
    interval = idle.get("interval_seconds")

    if peak is None or peak < 0:
        failures.append(
            "idle_memory_peak_invalid"
        )
    elif peak >= IDLE_MEMORY_LIMIT_BYTES:
        failures.append(
            "idle_memory_limit_exceeded"
        )
    if average is None or average < 0:
        failures.append(
            "idle_memory_average_invalid"
        )
    elif (
        peak is not None
        and average > peak
    ):
        failures.append(
            "idle_memory_average_exceeds_peak"
        )

    if (
        reported_limit
        != IDLE_MEMORY_LIMIT_BYTES
    ):
        failures.append(
            "idle_memory_limit_mismatch"
        )
    if idle.get("passed") is not True:
        failures.append(
            "reported_idle_gate_failed"
        )

    if (
        settle is None
        or settle < IDLE_MIN_SETTLE_SECONDS
    ):
        failures.append(
            "idle_settle_window_insufficient"
        )
    if (
        samples is None
        or samples < IDLE_MIN_SAMPLES
    ):
        failures.append(
            "idle_sample_count_insufficient"
        )
    if (
        isinstance(interval, bool)
        or not isinstance(
            interval,
            (int, float),
        )
        or interval <= 0
    ):
        failures.append(
            "idle_sample_interval_invalid"
        )

    services = idle.get("services")
    if not isinstance(services, dict):
        failures.append(
            "idle_services_missing"
        )
        services = {}
    if set(services) != set(
        CORE_SERVICES
    ):
        failures.append(
            "idle_services_incomplete"
        )
    else:
        for service in CORE_SERVICES:
            value = services[service]
            if not isinstance(value, dict):
                failures.append(
                    f"idle_service_invalid:{service}"
                )
                continue
            service_peak = integer(
                value.get(
                    "memory_peak_bytes"
                )
            )
            service_average = integer(
                value.get(
                    "memory_avg_bytes"
                )
            )
            if (
                service_peak is None
                or service_peak < 0
                or service_average is None
                or service_average < 0
                or service_average
                > service_peak
            ):
                failures.append(
                    f"idle_service_memory_invalid:{service}"
                )

    containers = report.get("containers")
    recorded_images: dict[str, str] = {}
    if isinstance(containers, list):
        for item in containers:
            if not isinstance(item, dict):
                continue
            service = item.get("service")
            image_id = item.get("image_id")
            if (
                isinstance(service, str)
                and service in CORE_SERVICES
                and isinstance(image_id, str)
            ):
                recorded_images[
                    service
                ] = image_id

    if set(recorded_images) != set(
        CORE_SERVICES
    ):
        failures.append(
            "recorded_core_images_incomplete"
        )
    if set(current_images) != set(
        CORE_SERVICES
    ):
        failures.append(
            "current_core_images_incomplete"
        )
    elif recorded_images != current_images:
        failures.append(
            "core_image_identity_changed"
        )

    return {
        "check": "idle",
        "passed": not failures,
        "generated_at": (
            generated_at.isoformat()
            if generated_at is not None
            else None
        ),
        "age_seconds": age_seconds,
        "max_age_hours": max_age_hours,
        "peak_bytes": peak,
        "average_bytes": average,
        "limit_bytes": (
            IDLE_MEMORY_LIMIT_BYTES
        ),
        "headroom_bytes": (
            IDLE_MEMORY_LIMIT_BYTES - peak
            if peak is not None
            else None
        ),
        "settle_seconds": settle,
        "samples": samples,
        "interval_seconds": interval,
        "recorded_images": recorded_images,
        "current_images": current_images,
        "failures": failures,
    }


def run(
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT_DIR,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def current_core_images(
    env_file: Path,
) -> dict[str, str]:
    images: dict[str, str] = {}
    for service in CORE_SERVICES:
        container = run(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_file),
                "-f",
                str(COMPOSE_FILE),
                "ps",
                "-q",
                service,
            ]
        ).stdout.strip()
        if not container:
            raise RuntimeError(
                f"Core container is unavailable: {service}"
            )
        image_id = run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.Image}}",
                container,
            ]
        ).stdout.strip()
        if not image_id.startswith("sha256:"):
            raise RuntimeError(
                f"invalid image identity for {service}"
            )
        images[service] = image_id
    return images


def main() -> int:
    args = parser().parse_args()
    env_file = Path(
        os.environ.get(
            "ZERO_NVR_ENV_FILE",
            ROOT_DIR / ".env",
        )
    )
    if not env_file.is_file():
        raise RuntimeError(".env is missing")

    values = read_env_file(env_file)
    data_root = host_path(
        values.get(
            "ZERO_NVR_DATA_PATH",
            "./data/zero-nvr",
        )
    )
    report_path = (
        data_root
        / "release-validation"
        / "latest-resource-baseline.json"
    )
    if not report_path.is_file():
        raise RuntimeError(
            "resource baseline evidence is missing; "
            "run ./deploy.sh resource-baseline first"
        )

    report = json.loads(
        report_path.read_text(
            encoding="utf-8"
        )
    )
    current_images = current_core_images(
        env_file
    )
    if args.check == "static":
        result = validate_static(
            report,
            current_images=current_images,
            max_age_hours=args.max_age_hours,
            now=datetime.now(UTC),
        )
    else:
        result = validate_idle(
            report,
            current_images=current_images,
            max_age_hours=args.max_age_hours,
            now=datetime.now(UTC),
        )
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
