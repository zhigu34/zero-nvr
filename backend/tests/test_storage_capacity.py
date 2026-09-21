from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from app.core.errors import ApiError
from app.modules.storage.capacity import (
    LocalStorageCapacityService,
)
from app.modules.storage.models import StorageTarget
from app.modules.storage.recording_resolver import (
    LocalRecordingTarget,
    RecordingStorageResolver,
)


def fake_statvfs(
    *,
    used_percent: int,
):
    blocks = 10_000
    free = int(
        blocks
        * (100 - used_percent)
        / 100
    )
    return SimpleNamespace(
        f_blocks=blocks,
        f_bavail=free,
        f_frsize=1024,
    )


def test_watermark_defaults_and_validation() -> None:
    defaults = (
        LocalStorageCapacityService
        .watermarks({})
    )
    assert defaults.warning_percent == 80
    assert defaults.high_percent == 85
    assert defaults.critical_percent == 95

    with pytest.raises(
        ApiError
    ) as captured:
        LocalStorageCapacityService.watermarks(
            {
                "warning_used_percent": 90,
                "high_used_percent": 85,
                "critical_used_percent": 95,
            }
        )
    assert (
        captured.value.code
        == "storage_watermark_invalid"
    )


def test_critical_capacity_blocks_new_recording_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.storage.capacity.os.statvfs",
        lambda _root: fake_statvfs(
            used_percent=96
        ),
    )
    target = StorageTarget(
        id=uuid.uuid4(),
        type="local",
        role="recording",
        name="Local",
        enabled=True,
        config_json={
            "path": str(tmp_path),
            "warning_used_percent": 80,
            "high_used_percent": 85,
            "critical_used_percent": 95,
        },
    )
    resolved = LocalRecordingTarget(
        target=target,
        root=tmp_path,
    )

    with pytest.raises(
        ApiError
    ) as captured:
        RecordingStorageResolver.ensure_write_capacity(
            resolved
        )
    assert captured.value.status_code == 507
    assert (
        captured.value.code
        == "recording_storage_capacity_critical"
    )
    assert (
        captured.value.details[
            "critical_percent"
        ]
        == 95
    )


def test_high_capacity_is_pressure_but_not_hard_write_stop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.storage.capacity.os.statvfs",
        lambda _root: fake_statvfs(
            used_percent=88
        ),
    )
    capacity = (
        LocalStorageCapacityService
        .ensure_write_capacity(
            root=tmp_path,
            config={},
        )
    )
    assert capacity.level == "high"
    assert capacity.used_percent == pytest.approx(
        88.0
    )
