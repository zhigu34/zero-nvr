from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parent
    / "resource_check.py"
)
SPEC = importlib.util.spec_from_file_location(
    "resource_check",
    MODULE_PATH,
)
assert SPEC is not None
assert SPEC.loader is not None
module = importlib.util.module_from_spec(
    SPEC
)
SPEC.loader.exec_module(module)


NOW = datetime(
    2026,
    9,
    24,
    12,
    0,
    tzinfo=UTC,
)
IMAGES = {
    "zero-nvr": "sha256:" + "1" * 64,
    "zero-nvr-worker": "sha256:" + "1" * 64,
    "zlmediakit": "sha256:" + "2" * 64,
}


def report(
    *,
    total: int = 1_500_000_000,
    generated_at: datetime | None = None,
) -> dict:
    image = 1_300_000_000
    writable = 100_000_000
    initial = 80_000_000
    logs = total - image - writable - initial
    return {
        "format": "zero-nvr.resource-baseline",
        "format_version": 1,
        "profile": "r1-clean-core-idle",
        "generated_at": (
            generated_at or NOW
        ).isoformat(),
        "clean_core": {
            "configured_cameras": 0,
            "enabled_cameras": 0,
            "optional_compose_profiles": [],
        },
        "static_footprint": {
            "passed": (
                total
                < module.STATIC_LIMIT_BYTES
            ),
            "total_bytes": total,
            "image_virtual_bytes_conservative": image,
            "container_writable_bytes": writable,
            "initial_product_state_bytes": initial,
            "data_bytes": 70_000_000,
            "env_bytes": 5_000_000,
            "generated_zlm_config_bytes": 5_000_000,
            "current_log_stream_bytes": logs,
        },
        "idle_runtime": {
            "passed": True,
            "settle_seconds": 60,
            "samples": 5,
            "interval_seconds": 2.0,
            "core_memory_avg_bytes": (
                700_000_000
            ),
            "core_memory_peak_bytes": (
                800_000_000
            ),
            "core_memory_limit_bytes": (
                module.IDLE_MEMORY_LIMIT_BYTES
            ),
            "services": {
                service: {
                    "memory_avg_bytes": (
                        200_000_000
                    ),
                    "memory_peak_bytes": (
                        250_000_000
                    ),
                }
                for service in IMAGES
            },
        },
        "containers": [
            {
                "service": service,
                "image_id": image_id,
            }
            for service, image_id in IMAGES.items()
        ],
    }


def validate(value: dict) -> dict:
    return module.validate_static(
        value,
        current_images=IMAGES,
        max_age_hours=168,
        now=NOW,
    )


def test_valid_static_evidence() -> None:
    result = validate(report())
    assert result["passed"] is True
    assert result["failures"] == []
    assert result["headroom_bytes"] > 0


def test_rejects_limit_exceeded() -> None:
    result = validate(
        report(
            total=module.STATIC_LIMIT_BYTES
        )
    )
    assert result["passed"] is False
    assert (
        "static_footprint_limit_exceeded"
        in result["failures"]
    )


def test_rejects_stale_evidence() -> None:
    result = validate(
        report(
            generated_at=(
                NOW
                - timedelta(days=8)
            )
        )
    )
    assert result["passed"] is False
    assert "evidence_stale" in result["failures"]


def test_rejects_image_change() -> None:
    value = report()
    current = dict(IMAGES)
    current["zlmediakit"] = (
        "sha256:" + "3" * 64
    )
    result = module.validate_static(
        value,
        current_images=current,
        max_age_hours=168,
        now=NOW,
    )
    assert result["passed"] is False
    assert (
        "core_image_identity_changed"
        in result["failures"]
    )


def test_rejects_tampered_total() -> None:
    value = report()
    value["static_footprint"][
        "total_bytes"
    ] -= 1
    result = validate(value)
    assert result["passed"] is False
    assert (
        "static_total_mismatch"
        in result["failures"]
    )


def validate_idle(
    value: dict,
) -> dict:
    return module.validate_idle(
        value,
        current_images=IMAGES,
        max_age_hours=168,
        now=NOW,
    )


def test_valid_idle_evidence() -> None:
    result = validate_idle(report())
    assert result["passed"] is True
    assert result["failures"] == []
    assert result["headroom_bytes"] > 0
    assert result["settle_seconds"] == 60
    assert result["samples"] == 5


def test_rejects_idle_memory_limit() -> None:
    value = report()
    value["idle_runtime"][
        "core_memory_peak_bytes"
    ] = module.IDLE_MEMORY_LIMIT_BYTES
    value["idle_runtime"]["passed"] = False
    result = validate_idle(value)
    assert result["passed"] is False
    assert (
        "idle_memory_limit_exceeded"
        in result["failures"]
    )


def test_rejects_short_idle_methodology() -> None:
    value = report()
    value["idle_runtime"][
        "settle_seconds"
    ] = 30
    value["idle_runtime"]["samples"] = 4
    result = validate_idle(value)
    assert result["passed"] is False
    assert (
        "idle_settle_window_insufficient"
        in result["failures"]
    )
    assert (
        "idle_sample_count_insufficient"
        in result["failures"]
    )


def test_rejects_idle_image_change() -> None:
    current = dict(IMAGES)
    current["zero-nvr"] = (
        "sha256:" + "4" * 64
    )
    result = module.validate_idle(
        report(),
        current_images=current,
        max_age_hours=168,
        now=NOW,
    )
    assert result["passed"] is False
    assert (
        "core_image_identity_changed"
        in result["failures"]
    )


if __name__ == "__main__":
    test_valid_static_evidence()
    test_rejects_limit_exceeded()
    test_rejects_stale_evidence()
    test_rejects_image_change()
    test_rejects_tampered_total()
    test_valid_idle_evidence()
    test_rejects_idle_memory_limit()
    test_rejects_short_idle_methodology()
    test_rejects_idle_image_change()
    print("resource evidence validation: ok")
