from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parent
    / "small_host_soak.py"
)
SPEC = importlib.util.spec_from_file_location(
    "small_host_soak",
    MODULE_PATH,
)
assert SPEC is not None
assert SPEC.loader is not None
module = importlib.util.module_from_spec(
    SPEC
)
SPEC.loader.exec_module(module)


def fake_final(
    expected: int,
) -> dict:
    return {
        "passed": True,
        "database": {
            "backend": "sqlite",
            "sqlite_wal_bytes": 4096,
        },
        "runtime": {
            "enabled_cameras": expected,
            "recording_expected_cameras": expected,
            "record_streams_online": expected,
        },
        "persistent_progress": [
            {
                "passed": True,
                "bytes_since_start": 1_000_000,
            }
            for _ in range(expected)
        ],
    }


def fake_resource(
    sample: int,
) -> dict:
    return {
        "sample": sample,
        "services": {
            service: {
                "memory_bytes": 100_000_000,
                "cpu_percent": 5.0,
                "restart_count": 0,
            }
            for service in module.CORE_SERVICES
        },
        "host_memory_available_bytes": 800_000_000,
        "sqlite_wal_bytes": 8192,
        "record_streams_online": 2,
    }


def build(
    *,
    duration: int = 3600,
    host_cpu: int = 2,
    host_memory: int = 2_000_000_000,
) -> dict:
    final = fake_final(2)
    samples = [
        {"passed": True, "failures": []}
    ]
    resources = [
        fake_resource(1),
        fake_resource(2),
    ]
    return module.build_report(
        expected=2,
        duration=duration,
        interval=30,
        started_at="2026-09-24T00:00:00Z",
        samples=samples,
        failed_sample_count=0,
        final_rc=0,
        final=final,
        resources=resources,
        host_cpu_count=host_cpu,
        host_memory_total_bytes=host_memory,
        initial_restarts={
            service: 0
            for service in module.CORE_SERVICES
        },
    )


def test_pass() -> None:
    report = build()
    assert report["passed"] is True
    assert (
        report["profile"]
        == "2-camera-small-host-soak"
    )
    assert (
        report["small_host"][
            "recording_write_bitrate_bps"
        ]
        > 0
    )


def test_short_duration_fails() -> None:
    report = build(duration=3599)
    assert report["passed"] is False
    assert (
        report["small_host"][
            "duration_gate_passed"
        ]
        is False
    )


def test_large_host_fails_class_gate() -> None:
    report = build(
        host_cpu=4,
        host_memory=8_000_000_000,
    )
    assert report["passed"] is False
    assert (
        report["small_host"][
            "host_class_matches"
        ]
        is False
    )


if __name__ == "__main__":
    test_pass()
    test_short_duration_fails()
    test_large_host_fails_class_gate()
    print("small-host soak helpers: ok")
