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


if __name__ == "__main__":
    test_valid_static_evidence()
    test_rejects_limit_exceeded()
    test_rejects_stale_evidence()
    test_rejects_image_change()
    test_rejects_tampered_total()
    print("resource static validation: ok")
