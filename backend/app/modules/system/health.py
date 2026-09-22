from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.integrations.frigate import (
    FrigateHttpAdapter,
    FrigateIntegrationError,
)
from app.integrations.zlm import (
    ZlmAdapter,
    ZlmIntegrationError,
)
from app.core.errors import ApiError
from app.modules.storage.capacity import (
    LocalStorageCapacityService,
)
from app.modules.storage.models import StorageTarget
from app.modules.system.models import SystemSetting

from .frigate import FrigateProviderSettingsService


class _Timeval(ctypes.Structure):
    _fields_ = [
        ("tv_sec", ctypes.c_long),
        ("tv_usec", ctypes.c_long),
    ]


class _Timex(ctypes.Structure):
    # Linux struct timex. Querying adjtimex with modes=0 is read-only and
    # observes the host kernel clock discipline from inside the container.
    _fields_ = [
        ("modes", ctypes.c_uint),
        ("offset", ctypes.c_long),
        ("freq", ctypes.c_long),
        ("maxerror", ctypes.c_long),
        ("esterror", ctypes.c_long),
        ("status", ctypes.c_int),
        ("constant", ctypes.c_long),
        ("precision", ctypes.c_long),
        ("tolerance", ctypes.c_long),
        ("time", _Timeval),
        ("tick", ctypes.c_long),
        ("ppsfreq", ctypes.c_long),
        ("jitter", ctypes.c_long),
        ("shift", ctypes.c_int),
        ("stabil", ctypes.c_long),
        ("jitcnt", ctypes.c_long),
        ("calcnt", ctypes.c_long),
        ("errcnt", ctypes.c_long),
        ("stbcnt", ctypes.c_long),
        ("tai", ctypes.c_int),
        ("reserved", ctypes.c_int * 11),
    ]


_STA_UNSYNC = 0x0040
_STA_NANO = 0x2000
_TIME_ERROR = 5


@dataclass(frozen=True, slots=True)
class HostClockKernelState:
    synchronized: bool
    time_state: int
    status_flags: int
    estimated_offset_ms: float
    estimated_error_ms: float
    max_error_ms: float
    tai_offset_seconds: int


def read_host_clock_kernel_state() -> HostClockKernelState | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL(
            None,
            use_errno=True,
        )
        adjtimex = libc.adjtimex
        adjtimex.argtypes = [
            ctypes.POINTER(_Timex)
        ]
        adjtimex.restype = ctypes.c_int
        value = _Timex()
        time_state = int(
            adjtimex(
                ctypes.byref(value)
            )
        )
    except (AttributeError, OSError):
        return None

    if time_state < 0:
        return None

    offset_divisor = (
        1_000_000.0
        if value.status & _STA_NANO
        else 1_000.0
    )
    return HostClockKernelState(
        synchronized=(
            time_state != _TIME_ERROR
            and not (
                value.status
                & _STA_UNSYNC
            )
        ),
        time_state=time_state,
        status_flags=int(
            value.status
        ),
        estimated_offset_ms=(
            float(value.offset)
            / offset_divisor
        ),
        estimated_error_ms=(
            float(value.esterror)
            / 1_000.0
        ),
        max_error_ms=(
            float(value.maxerror)
            / 1_000.0
        ),
        tai_offset_seconds=int(
            value.tai
        ),
    )


@dataclass(frozen=True, slots=True)
class HealthComponent:
    status: str
    message: str | None = None
    details: dict[str, object] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class ProductHealth:
    status: str
    components: dict[str, HealthComponent]


class SystemHealthService:
    worker_stale_seconds = 150
    reconciliation_stale_seconds = 20 * 60

    def __init__(
        self,
        settings: Settings,
        database: Database,
        *,
        frigate_mqtt_runtime: Any | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.frigate_mqtt_runtime = (
            frigate_mqtt_runtime
        )

    @property
    def worker_heartbeat_path(self) -> Path:
        return (
            self.settings.cache_dir
            / "runtime"
            / "worker-heartbeat.json"
        )

    @staticmethod
    def _overall(
        components: dict[str, HealthComponent],
    ) -> str:
        required = {
            "database",
            "zlmediakit",
            "storage",
        }
        for name in required:
            component = components.get(name)
            if (
                component is not None
                and component.status == "ERROR"
            ):
                return "ERROR"

        if any(
            component.status in {"ERROR", "DEGRADED"}
            for component in components.values()
        ):
            return "DEGRADED"
        return "OK"

    @staticmethod
    def _host_clock() -> HealthComponent:
        state = read_host_clock_kernel_state()
        base: dict[str, object] = {
            "canonical_timezone": "UTC",
            "checked_at": (
                datetime.now(
                    UTC
                ).isoformat()
            ),
            "source": "linux_adjtimex",
        }
        if state is None:
            return HealthComponent(
                status="DISABLED",
                message=(
                    "host_clock_sync_probe_unavailable"
                ),
                details=base,
            )

        details = {
            **base,
            "sync_state": (
                "synchronized"
                if state.synchronized
                else "unsynchronized"
            ),
            "kernel_time_state": (
                state.time_state
            ),
            "status_flags": (
                state.status_flags
            ),
            "estimated_offset_ms": round(
                state.estimated_offset_ms,
                3,
            ),
            "estimated_error_ms": round(
                state.estimated_error_ms,
                3,
            ),
            "max_error_ms": round(
                state.max_error_ms,
                3,
            ),
            "tai_offset_seconds": (
                state.tai_offset_seconds
            ),
        }
        if not state.synchronized:
            return HealthComponent(
                status="DEGRADED",
                message=(
                    "host_clock_unsynchronized"
                ),
                details=details,
            )
        return HealthComponent(
            status="OK",
            details=details,
        )

    def _database(self) -> HealthComponent:
        try:
            self.database.ping()
        except Exception:
            return HealthComponent(
                status="ERROR",
                message="database_unavailable",
            )

        backend = self.database.url.get_backend_name()
        details: dict[str, object] = {
            "backend": backend,
        }
        if not self.database.is_sqlite:
            return HealthComponent(
                status="OK",
                details=details,
            )

        try:
            runtime = self.database.sqlite_runtime_health()
        except Exception:
            return HealthComponent(
                status="DEGRADED",
                message="sqlite_health_probe_failed",
                details=details,
            )

        if runtime is None:
            return HealthComponent(
                status="DEGRADED",
                message="sqlite_health_probe_failed",
                details=details,
            )

        details.update(
            {
                "journal_mode": runtime.journal_mode,
                "busy_timeout_ms": runtime.busy_timeout_ms,
                "wal_autocheckpoint_pages": (
                    runtime.wal_autocheckpoint_pages
                ),
                "page_size_bytes": runtime.page_size_bytes,
                "wal_pages": runtime.wal_pages,
                "checkpointed_pages": (
                    runtime.checkpointed_pages
                ),
                "backlog_pages": runtime.backlog_pages,
                "wal_bytes": runtime.wal_bytes,
                "checkpoint_busy": (
                    runtime.checkpoint_busy
                ),
                "write_pressure": (
                    runtime.write_pressure
                ),
            }
        )

        if runtime.journal_mode != "wal":
            return HealthComponent(
                status="ERROR",
                message="sqlite_wal_disabled",
                details=details,
            )
        if runtime.write_pressure == "high":
            return HealthComponent(
                status="DEGRADED",
                message="sqlite_write_pressure_high",
                details=details,
            )
        if runtime.write_pressure == "elevated":
            return HealthComponent(
                status="DEGRADED",
                message=(
                    "sqlite_write_pressure_elevated"
                ),
                details=details,
            )
        return HealthComponent(
            status="OK",
            details=details,
        )

    def _worker(self) -> HealthComponent:
        path = self.worker_heartbeat_path
        try:
            age = time.time() - path.stat().st_mtime
        except FileNotFoundError:
            return HealthComponent(
                status="DEGRADED",
                message="worker_heartbeat_missing",
            )
        except OSError:
            return HealthComponent(
                status="DEGRADED",
                message="worker_heartbeat_unreadable",
            )

        if age > self.worker_stale_seconds:
            return HealthComponent(
                status="ERROR",
                message="worker_heartbeat_stale",
                details={
                    "age_seconds": int(age),
                },
            )
        return HealthComponent(
            status="OK",
            details={
                "age_seconds": max(0, int(age)),
            },
        )

    def _zlm(self) -> HealthComponent:
        if self.settings.zlm_api_secret is None:
            return HealthComponent(
                status="ERROR",
                message="zlm_not_configured",
            )
        try:
            with ZlmAdapter(
                self.settings,
                timeout_seconds=2.0,
            ) as adapter:
                version = adapter.version()
            return HealthComponent(
                status="OK",
                details={
                    "version": (
                        version.get("version")
                        or version.get("commit")
                        or "unknown"
                    )
                },
            )
        except ZlmIntegrationError as exc:
            return HealthComponent(
                status="ERROR",
                message=exc.code,
            )

    @staticmethod
    def _local_storage(
        targets: list[StorageTarget],
    ) -> HealthComponent:
        local = [
            target
            for target in targets
            if target.enabled
            and target.type == "local"
            and target.role == "recording"
        ]
        if not local:
            return HealthComponent(
                status="ERROR",
                message="recording_storage_not_configured",
            )

        target_details: list[
            dict[str, object]
        ] = []
        total_free = 0
        unavailable = 0
        warning = 0
        high = 0
        critical = 0

        for target in local:
            config = target.config_json or {}
            raw = config.get("path")
            base: dict[str, object] = {
                "id": str(target.id),
                "name": target.name,
            }
            if (
                not isinstance(raw, str)
                or not raw
            ):
                unavailable += 1
                target_details.append(
                    {
                        **base,
                        "level": "unavailable",
                        "error": (
                            "recording_storage_path_"
                            "unconfigured"
                        ),
                    }
                )
                continue

            try:
                capacity = (
                    LocalStorageCapacityService
                    .inspect(
                        root=Path(raw),
                        config=config,
                    )
                )
            except ApiError as exc:
                unavailable += 1
                target_details.append(
                    {
                        **base,
                        "path": raw,
                        "level": "unavailable",
                        "error": exc.code,
                    }
                )
                continue

            total_free += capacity.free_bytes
            if capacity.level == "warning":
                warning += 1
            elif capacity.level == "high":
                high += 1
            elif capacity.level == "critical":
                critical += 1

            target_details.append(
                {
                    **base,
                    "path": raw,
                    "level": capacity.level,
                    "used_percent": round(
                        capacity.used_percent,
                        2,
                    ),
                    "free_bytes": (
                        capacity.free_bytes
                    ),
                    "total_bytes": (
                        capacity.total_bytes
                    ),
                    "warning_percent": (
                        capacity.watermarks
                        .warning_percent
                    ),
                    "high_percent": (
                        capacity.watermarks
                        .high_percent
                    ),
                    "critical_percent": (
                        capacity.watermarks
                        .critical_percent
                    ),
                }
            )

        details: dict[str, object] = {
            "targets": len(local),
            "free_bytes": total_free,
            "unavailable_targets": unavailable,
            "warning_targets": warning,
            "high_targets": high,
            "critical_targets": critical,
            "target_details": target_details,
        }

        if unavailable:
            return HealthComponent(
                status="ERROR",
                message="recording_storage_unavailable",
                details=details,
            )
        if critical:
            return HealthComponent(
                status="ERROR",
                message=(
                    "recording_storage_capacity_"
                    "critical"
                ),
                details=details,
            )
        if high:
            return HealthComponent(
                status="DEGRADED",
                message="recording_storage_capacity_high",
                details=details,
            )
        if warning:
            return HealthComponent(
                status="DEGRADED",
                message=(
                    "recording_storage_capacity_"
                    "warning"
                ),
                details=details,
            )
        return HealthComponent(
            status="OK",
            details=details,
        )

    def _recording_reconciliation(
        self,
    ) -> HealthComponent:
        try:
            with self.database.session() as session:
                state = session.get(
                    SystemSetting,
                    "recording.reconciliation",
                )
                if state is None:
                    session.commit()
                    return HealthComponent(
                        status="DEGRADED",
                        message=(
                            "recording_reconciliation_pending"
                        ),
                    )
                payload = dict(
                    state.value_json
                    or {}
                )
                session.commit()
        except Exception:
            return HealthComponent(
                status="DEGRADED",
                message=(
                    "recording_reconciliation_unavailable"
                ),
            )

        raw_completed = payload.get(
            "last_completed_at"
        )
        if not isinstance(
            raw_completed,
            str,
        ):
            return HealthComponent(
                status="DEGRADED",
                message=(
                    "recording_reconciliation_pending"
                ),
            )
        try:
            completed = datetime.fromisoformat(
                raw_completed.replace(
                    "Z",
                    "+00:00",
                )
            )
            if completed.tzinfo is None:
                raise ValueError
            age = (
                datetime.now(
                    completed.tzinfo
                )
                - completed
            ).total_seconds()
        except ValueError:
            return HealthComponent(
                status="DEGRADED",
                message=(
                    "recording_reconciliation_state_invalid"
                ),
            )

        result = payload.get(
            "last_result"
        )
        details: dict[str, object] = {
            "age_seconds": max(
                0,
                int(age),
            ),
            "last_completed_at": (
                raw_completed
            ),
            "last_full_at": payload.get(
                "last_full_at"
            ),
        }
        if isinstance(result, dict):
            for key in (
                "full",
                "scanned_files",
                "recovered",
                "relinked",
                "missing",
                "ambiguous",
                "errors",
                "skipped_unsettled",
            ):
                if key in result:
                    details[key] = (
                        result[key]
                    )

        if (
            age
            > self.reconciliation_stale_seconds
        ):
            return HealthComponent(
                status="ERROR",
                message=(
                    "recording_reconciliation_stale"
                ),
                details=details,
            )

        errors = (
            int(
                result.get(
                    "errors",
                    0,
                )
            )
            if isinstance(
                result,
                dict,
            )
            else 0
        )
        missing = (
            int(
                result.get(
                    "missing",
                    0,
                )
            )
            if isinstance(
                result,
                dict,
            )
            else 0
        )
        ambiguous = (
            int(
                result.get(
                    "ambiguous",
                    0,
                )
            )
            if isinstance(
                result,
                dict,
            )
            else 0
        )
        if errors:
            return HealthComponent(
                status="DEGRADED",
                message=(
                    "recording_reconciliation_errors"
                ),
                details=details,
            )
        if missing:
            return HealthComponent(
                status="DEGRADED",
                message=(
                    "recording_media_missing"
                ),
                details=details,
            )
        if ambiguous:
            return HealthComponent(
                status="DEGRADED",
                message=(
                    "recording_media_ambiguous"
                ),
                details=details,
            )
        return HealthComponent(
            status="OK",
            details=details,
        )

    def _frigate(
        self,
        config,
    ) -> HealthComponent:
        if config is None or not config.enabled:
            return HealthComponent(
                status="DISABLED",
            )
        try:
            with FrigateHttpAdapter(
                base_url=config.base_url,
                bearer_token=(
                    config.credentials.http_bearer_token
                ),
                username=(
                    config.credentials.http_username
                ),
                password=(
                    config.credentials.http_password
                ),
                timeout_seconds=2.0,
            ) as adapter:
                version = adapter.version()
        except FrigateIntegrationError as exc:
            return HealthComponent(
                status="ERROR",
                message=exc.code,
            )

        details: dict[str, object] = {
            "version": version.version or "unknown",
            "mode": config.mode,
        }
        if config.mqtt_enabled:
            runtime = self.frigate_mqtt_runtime
            if runtime is None:
                return HealthComponent(
                    status="DEGRADED",
                    message="frigate_mqtt_runtime_unavailable",
                    details=details,
                )
            status = runtime.status()
            details["mqtt_connected"] = status.connected
            if not status.connected:
                return HealthComponent(
                    status="DEGRADED",
                    message=(
                        status.last_error
                        or "frigate_mqtt_disconnected"
                    ),
                    details=details,
                )

        return HealthComponent(
            status="OK",
            details=details,
        )

    def collect(self) -> ProductHealth:
        database_health = self._database()

        frigate_config = None
        targets: list[StorageTarget] = []
        if database_health.status == "OK":
            try:
                with self.database.session() as session:
                    frigate_config = (
                        FrigateProviderSettingsService(
                            self.settings
                        ).get(session)
                    )
                    targets = list(
                        session.scalars(
                            select(StorageTarget).where(
                                StorageTarget.enabled.is_(
                                    True
                                )
                            )
                        )
                    )
                    session.commit()
            except Exception:
                database_health = HealthComponent(
                    status="ERROR",
                    message="database_query_failed",
                )

        rclone_count = len(
            [
                target
                for target in targets
                if target.type == "rclone"
                and target.enabled
            ]
        )
        components = {
            "database": database_health,
            "host_clock": self._host_clock(),
            "worker": self._worker(),
            "zlmediakit": self._zlm(),
            "storage": self._local_storage(
                targets
            ),
            "recording_reconciliation": (
                self._recording_reconciliation()
            ),
            "frigate": self._frigate(
                frigate_config
            ),
            "archive": HealthComponent(
                status=(
                    "OK"
                    if rclone_count
                    else "DISABLED"
                ),
                details={
                    "configured_targets": rclone_count,
                },
            ),
        }
        return ProductHealth(
            status=self._overall(components),
            components=components,
        )


def write_worker_heartbeat(
    settings: Settings,
) -> Path:
    path = (
        settings.cache_dir
        / "runtime"
        / "worker-heartbeat.json"
    )
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"pid": os.getpid(), "time": time.time()},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
