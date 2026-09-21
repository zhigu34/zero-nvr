from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.errors import ApiError


StorageCapacityLevel = Literal[
    "normal",
    "warning",
    "high",
    "critical",
]


@dataclass(frozen=True, slots=True)
class LocalStorageWatermarks:
    warning_percent: int = 80
    high_percent: int = 85
    critical_percent: int = 95


@dataclass(frozen=True, slots=True)
class LocalStorageCapacity:
    total_bytes: int
    free_bytes: int
    used_bytes: int
    used_percent: float
    level: StorageCapacityLevel
    watermarks: LocalStorageWatermarks


class LocalStorageCapacityService:
    warning_key = "warning_used_percent"
    high_key = "high_used_percent"
    critical_key = "critical_used_percent"

    @classmethod
    def watermarks(
        cls,
        config: dict[str, object],
    ) -> LocalStorageWatermarks:
        values: dict[str, int] = {}
        defaults = {
            cls.warning_key: 80,
            cls.high_key: 85,
            cls.critical_key: 95,
        }
        for key, default in defaults.items():
            raw = config.get(
                key,
                default,
            )
            if (
                isinstance(raw, bool)
                or not isinstance(raw, int)
            ):
                raise ApiError(
                    status_code=400,
                    code=(
                        "storage_watermark_invalid"
                    ),
                    message=(
                        "Storage watermarks must "
                        "be whole-number percentages."
                    ),
                )
            values[key] = raw

        warning = values[
            cls.warning_key
        ]
        high = values[
            cls.high_key
        ]
        critical = values[
            cls.critical_key
        ]
        if not (
            1
            <= warning
            < high
            < critical
            <= 99
        ):
            raise ApiError(
                status_code=400,
                code="storage_watermark_invalid",
                message=(
                    "Storage watermarks must "
                    "satisfy 1 <= warning < high "
                    "< critical <= 99."
                ),
            )
        return LocalStorageWatermarks(
            warning_percent=warning,
            high_percent=high,
            critical_percent=critical,
        )

    @classmethod
    def normalize_config(
        cls,
        config: dict[str, object],
    ) -> dict[str, int]:
        watermarks = cls.watermarks(
            config
        )
        return {
            cls.warning_key:
                watermarks.warning_percent,
            cls.high_key:
                watermarks.high_percent,
            cls.critical_key:
                watermarks.critical_percent,
        }

    @classmethod
    def inspect(
        cls,
        *,
        root: Path,
        config: dict[str, object],
    ) -> LocalStorageCapacity:
        watermarks = cls.watermarks(
            config
        )
        try:
            stats = os.statvfs(root)
        except OSError as exc:
            raise ApiError(
                status_code=409,
                code=(
                    "storage_target_path_unavailable"
                ),
                message=(
                    "Local storage target path "
                    "is unavailable."
                ),
            ) from exc

        total_bytes = (
            stats.f_blocks
            * stats.f_frsize
        )
        free_bytes = (
            stats.f_bavail
            * stats.f_frsize
        )
        if total_bytes <= 0:
            raise ApiError(
                status_code=409,
                code=(
                    "storage_capacity_unavailable"
                ),
                message=(
                    "Local storage capacity "
                    "could not be determined."
                ),
            )

        used_bytes = max(
            0,
            total_bytes - free_bytes,
        )
        used_percent = min(
            100.0,
            max(
                0.0,
                (
                    used_bytes
                    / total_bytes
                )
                * 100.0,
            ),
        )
        if (
            used_percent
            >= watermarks.critical_percent
        ):
            level: StorageCapacityLevel = (
                "critical"
            )
        elif (
            used_percent
            >= watermarks.high_percent
        ):
            level = "high"
        elif (
            used_percent
            >= watermarks.warning_percent
        ):
            level = "warning"
        else:
            level = "normal"

        return LocalStorageCapacity(
            total_bytes=total_bytes,
            free_bytes=free_bytes,
            used_bytes=used_bytes,
            used_percent=used_percent,
            level=level,
            watermarks=watermarks,
        )

    @classmethod
    def ensure_write_capacity(
        cls,
        *,
        root: Path,
        config: dict[str, object],
    ) -> LocalStorageCapacity:
        capacity = cls.inspect(
            root=root,
            config=config,
        )
        if capacity.level == "critical":
            raise ApiError(
                status_code=507,
                code=(
                    "recording_storage_"
                    "capacity_critical"
                ),
                message=(
                    "Recording storage is at "
                    "the critical disk watermark."
                ),
                details={
                    "used_percent": round(
                        capacity.used_percent,
                        2,
                    ),
                    "critical_percent": (
                        capacity.watermarks
                        .critical_percent
                    ),
                    "free_bytes": (
                        capacity.free_bytes
                    ),
                },
            )
        return capacity
