#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT_DIR / "docker-compose.yml"
SMALL_HOST_MEMORY_MAX_BYTES = 2_684_354_560
SMALL_HOST_CPU_MAX = 2
MIN_DURATION_SECONDS = 3600
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
            "Plan 04 R2/R3 real-host small-host soak "
            "collector"
        )
    )
    result.add_argument(
        "expected_cameras",
        type=int,
        choices=(2, 4),
    )
    result.add_argument(
        "--duration",
        type=positive_int,
        default=MIN_DURATION_SECONDS,
    )
    result.add_argument(
        "--interval",
        type=positive_int,
        default=30,
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


def run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT_DIR,
        env=env,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class Runtime:
    def __init__(
        self,
        env_file: Path,
        values: dict[str, str],
    ) -> None:
        self.env_file = env_file
        self.values = values
        self.env = dict(os.environ)
        self.env["ZERO_NVR_ENV_FILE"] = str(
            env_file
        )
        self.env["COMPOSE_PROFILES"] = values.get(
            "COMPOSE_PROFILES",
            "",
        )

    def compose(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return run(
            [
                "docker",
                "compose",
                "--env-file",
                str(self.env_file),
                "-f",
                str(COMPOSE_FILE),
                *args,
            ],
            env=self.env,
            check=check,
        )

    def container_id(self, service: str) -> str:
        value = self.compose(
            "ps",
            "-q",
            service,
        ).stdout.strip()
        if not value:
            raise RuntimeError(
                f"Core container is unavailable: {service}"
            )
        return value


def meminfo_bytes(name: str) -> int:
    prefix = f"{name}:"
    for line in Path("/proc/meminfo").read_text(
        encoding="utf-8"
    ).splitlines():
        if line.startswith(prefix):
            return int(line.split()[1]) * 1024
    raise RuntimeError(
        f"/proc/meminfo does not contain {name}"
    )


def size_to_bytes(raw: str) -> int:
    token = raw.strip().split()[0]
    number = ""
    unit = ""
    for char in token:
        if char.isdigit() or char == ".":
            number += char
        else:
            unit += char
    if not number:
        raise ValueError(
            f"invalid Docker memory value: {raw}"
        )
    multipliers = {
        "": 1,
        "B": 1,
        "kB": 1000,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "TiB": 1024**4,
    }
    if unit not in multipliers:
        raise ValueError(
            f"unsupported Docker memory unit: {unit}"
        )
    return int(
        float(number) * multipliers[unit]
    )


def docker_stats(container_id: str) -> tuple[int, float]:
    completed = run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{.MemUsage}}|{{.CPUPerc}}",
            container_id,
        ]
    )
    memory_raw, cpu_raw = (
        completed.stdout.strip().split("|", 1)
    )
    memory_used = memory_raw.split("/", 1)[0].strip()
    return (
        size_to_bytes(memory_used),
        float(cpu_raw.rstrip("%")),
    )


def restart_count(container_id: str) -> int:
    completed = run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.RestartCount}}",
            container_id,
        ]
    )
    return int(completed.stdout.strip())


def soak_status(
    runtime: Runtime,
    *,
    expected: int,
    started_at: str,
    require_progress: bool,
) -> tuple[int, dict[str, Any]]:
    args = [
        "exec",
        "-T",
        "zero-nvr",
        "python",
        "-m",
        "app.cli",
        "soak-status",
        "--expected-cameras",
        str(expected),
        "--since",
        started_at,
    ]
    if require_progress:
        args.append("--require-progress")

    completed = runtime.compose(
        *args,
        check=False,
    )
    raw = completed.stdout.strip()
    if not raw:
        return (
            completed.returncode or 1,
            {
                "passed": False,
                "failures": [
                    "sample_output_missing"
                ],
            },
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "soak-status returned invalid JSON"
        ) from exc
    return completed.returncode, payload


def collect_resource_sample(
    container_ids: dict[str, str],
    sample: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    services: dict[str, dict[str, Any]] = {}
    for service in CORE_SERVICES:
        memory, cpu = docker_stats(
            container_ids[service]
        )
        services[service] = {
            "memory_bytes": memory,
            "cpu_percent": cpu,
            "restart_count": restart_count(
                container_ids[service]
            ),
        }

    database = sample.get("database") or {}
    runtime = sample.get("runtime") or {}
    return {
        "sample": index,
        "services": services,
        "host_memory_available_bytes": (
            meminfo_bytes("MemAvailable")
        ),
        "sqlite_wal_bytes": int(
            database.get("sqlite_wal_bytes")
            or 0
        ),
        "record_streams_online": int(
            runtime.get("record_streams_online")
            or 0
        ),
    }


def build_report(
    *,
    expected: int,
    duration: int,
    interval: int,
    started_at: str,
    samples: list[dict[str, Any]],
    failed_sample_count: int,
    final_rc: int,
    final: dict[str, Any],
    resources: list[dict[str, Any]],
    host_cpu_count: int,
    host_memory_total_bytes: int,
    initial_restarts: dict[str, int],
) -> dict[str, Any]:
    failure_counts: collections.Counter[str] = (
        collections.Counter()
    )
    for sample in samples:
        for failure in sample.get(
            "failures",
            [],
        ):
            failure_counts[str(failure)] += 1

    functional_passed = (
        failed_sample_count == 0
        and final_rc == 0
        and bool(final.get("passed"))
    )

    runtime = final.get("runtime") or {}
    database = final.get("database") or {}
    progress = (
        final.get("persistent_progress")
        or []
    )

    duration_ok = duration >= MIN_DURATION_SECONDS
    sqlite_ok = (
        database.get("backend") == "sqlite"
    )
    exact_workload = (
        int(
            runtime.get("enabled_cameras")
            or 0
        )
        == expected
        and int(
            runtime.get(
                "recording_expected_cameras"
            )
            or 0
        )
        == expected
    )
    continuous_recording = (
        len(progress) == expected
        and all(
            bool(item.get("passed"))
            for item in progress
        )
    )
    host_class_matches = (
        host_cpu_count <= SMALL_HOST_CPU_MAX
        and host_memory_total_bytes
        <= SMALL_HOST_MEMORY_MAX_BYTES
    )

    restart_delta: dict[str, int] = {}
    for service in CORE_SERVICES:
        maximum = max(
            int(
                row["services"][service][
                    "restart_count"
                ]
            )
            for row in resources
        )
        restart_delta[service] = (
            maximum
            - initial_restarts[service]
        )
    no_restarts = all(
        value == 0
        for value in restart_delta.values()
    )

    core_memory = [
        sum(
            int(
                row["services"][service][
                    "memory_bytes"
                ]
            )
            for service in CORE_SERVICES
        )
        for row in resources
    ]
    core_cpu = [
        sum(
            float(
                row["services"][service][
                    "cpu_percent"
                ]
            )
            for service in CORE_SERVICES
        )
        for row in resources
    ]

    bytes_written = sum(
        int(
            item.get("bytes_since_start")
            or 0
        )
        for item in progress
    )

    acceptance_passed = all(
        (
            functional_passed,
            duration_ok,
            sqlite_ok,
            exact_workload,
            continuous_recording,
            host_class_matches,
            no_restarts,
        )
    )

    return {
        "format": "zero-nvr.small-host-soak",
        "format_version": 1,
        "profile": (
            f"{expected}-camera-small-host-soak"
        ),
        "generated_at": datetime.now(
            UTC
        ).isoformat(),
        "started_at": started_at,
        "duration_seconds": duration,
        "interval_seconds": interval,
        "sample_count": len(samples),
        "failed_sample_count": (
            failed_sample_count
        ),
        "sample_failure_counts": dict(
            sorted(failure_counts.items())
        ),
        "functional_passed": (
            functional_passed
        ),
        "passed": acceptance_passed,
        "final": final,
        "small_host": {
            "minimum_duration_seconds": (
                MIN_DURATION_SECONDS
            ),
            "duration_gate_passed": (
                duration_ok
            ),
            "database_sqlite": sqlite_ok,
            "exact_camera_workload": (
                exact_workload
            ),
            "continuous_recording": (
                continuous_recording
            ),
            "host_class_matches": (
                host_class_matches
            ),
            "target_host_cpu_cores": (
                SMALL_HOST_CPU_MAX
            ),
            "target_host_memory_bytes_max": (
                SMALL_HOST_MEMORY_MAX_BYTES
            ),
            "host_cpu_count": (
                host_cpu_count
            ),
            "host_memory_total_bytes": (
                host_memory_total_bytes
            ),
            "host_memory_available_min_bytes": min(
                int(
                    row[
                        "host_memory_available_bytes"
                    ]
                )
                for row in resources
            ),
            "core_memory_avg_bytes": int(
                statistics.mean(
                    core_memory
                )
            ),
            "core_memory_peak_bytes": max(
                core_memory
            ),
            "core_cpu_avg_percent": round(
                statistics.mean(core_cpu),
                3,
            ),
            "core_cpu_peak_percent": round(
                max(core_cpu),
                3,
            ),
            "sqlite_wal_peak_bytes": max(
                int(
                    row[
                        "sqlite_wal_bytes"
                    ]
                )
                for row in resources
            ),
            "record_streams_online_min": min(
                int(
                    row[
                        "record_streams_online"
                    ]
                )
                for row in resources
            ),
            "recording_write_bitrate_bps": (
                int(
                    bytes_written
                    * 8
                    / duration
                )
                if duration > 0
                else 0
            ),
            "container_restart_delta": (
                restart_delta
            ),
            "no_container_restarts": (
                no_restarts
            ),
            "resource_samples": resources,
        },
        "methodology": {
            "workload": (
                "exactly the requested number of "
                "persistent-recording cameras"
            ),
            "resource_sampling": (
                "Docker/cgroup memory and CPU for "
                "API, worker, and ZLMediaKit plus "
                "host MemAvailable, SQLite WAL size, "
                "RECORD streams, and restart counts"
            ),
            "host_class": (
                "acceptance requires <=2 CPU cores "
                "and <=2.5 GiB host RAM"
            ),
        },
    }


def persist_report(
    report: dict[str, Any],
    *,
    expected: int,
    values: dict[str, str],
) -> Path:
    data_root = host_path(
        values.get(
            "ZERO_NVR_DATA_PATH",
            "./data/zero-nvr",
        )
    )
    report_dir = (
        data_root
        / "release-validation"
    )
    report_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    target = report_dir / (
        f"latest-small-host-{expected}.json"
    )
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=report_dir,
        prefix=".small-host.",
        delete=False,
    ) as handle:
        json.dump(
            report,
            handle,
            sort_keys=True,
        )
        handle.write("\n")
        temporary = Path(handle.name)
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)
    return target


def main() -> int:
    args = parser().parse_args()
    env_file = Path(
        os.environ.get(
            "ZERO_NVR_ENV_FILE",
            ROOT_DIR / ".env",
        )
    )
    if not env_file.is_file():
        raise RuntimeError(
            ".env is missing"
        )

    values = read_env_file(env_file)
    if values.get(
        "COMPOSE_PROFILES",
        "",
    ).strip():
        raise RuntimeError(
            "small-host soak requires "
            "Core-only COMPOSE_PROFILES="
        )

    run(["docker", "compose", "version"])
    run(["docker", "info"])

    check_env = dict(os.environ)
    check_env["ZERO_NVR_ENV_FILE"] = (
        str(env_file)
    )
    run(
        [
            str(
                ROOT_DIR
                / "scripts"
                / "check.sh"
            )
        ],
        env=check_env,
    )

    runtime = Runtime(
        env_file,
        values,
    )
    running = {
        item
        for item in runtime.compose(
            "ps",
            "--status",
            "running",
            "--services",
        ).stdout.split()
        if item
    }
    if running != set(CORE_SERVICES):
        raise RuntimeError(
            "small-host soak requires exactly "
            "the three running Core services"
        )

    container_ids = {
        service: runtime.container_id(
            service
        )
        for service in CORE_SERVICES
    }
    initial_restarts = {
        service: restart_count(
            container_ids[service]
        )
        for service in CORE_SERVICES
    }
    host_cpu_count = (
        os.cpu_count()
        or 1
    )
    host_memory_total_bytes = (
        meminfo_bytes("MemTotal")
    )

    started_at = datetime.now(
        UTC
    ).replace(
        microsecond=0
    ).isoformat().replace(
        "+00:00",
        "Z",
    )

    samples: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    failed = 0
    elapsed = 0

    while elapsed < args.duration:
        rc, sample = soak_status(
            runtime,
            expected=args.expected_cameras,
            started_at=started_at,
            require_progress=False,
        )
        samples.append(sample)
        resources.append(
            collect_resource_sample(
                container_ids,
                sample,
                len(samples),
            )
        )
        if rc != 0:
            failed += 1

        remaining = (
            args.duration
            - elapsed
        )
        sleep_for = min(
            args.interval,
            remaining,
        )
        time.sleep(sleep_for)
        elapsed += sleep_for

    final_rc, final = soak_status(
        runtime,
        expected=args.expected_cameras,
        started_at=started_at,
        require_progress=True,
    )
    resources.append(
        collect_resource_sample(
            container_ids,
            final,
            len(samples) + 1,
        )
    )

    report = build_report(
        expected=args.expected_cameras,
        duration=args.duration,
        interval=args.interval,
        started_at=started_at,
        samples=samples,
        failed_sample_count=failed,
        final_rc=final_rc,
        final=final,
        resources=resources,
        host_cpu_count=(
            host_cpu_count
        ),
        host_memory_total_bytes=(
            host_memory_total_bytes
        ),
        initial_restarts=(
            initial_restarts
        ),
    )
    persist_report(
        report,
        expected=args.expected_cameras,
        values=values,
    )
    print(
        json.dumps(
            report,
            sort_keys=True,
        )
    )
    return (
        0
        if report["passed"]
        else 1
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"error: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
