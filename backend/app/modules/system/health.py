from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
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
from app.modules.storage.models import StorageTarget

from .frigate import FrigateProviderSettingsService


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

    def _database(self) -> HealthComponent:
        try:
            self.database.ping()
            return HealthComponent(status="OK")
        except Exception:
            return HealthComponent(
                status="ERROR",
                message="database_unavailable",
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

        details: dict[str, object] = {
            "targets": len(local),
        }
        errors = 0
        total_free = 0
        for target in local:
            raw = target.config_json.get("path")
            if not isinstance(raw, str) or not raw:
                errors += 1
                continue
            path = Path(raw)
            try:
                usage = shutil.disk_usage(path)
                total_free += usage.free
            except OSError:
                errors += 1

        details["free_bytes"] = total_free
        if errors:
            details["unavailable_targets"] = errors
            return HealthComponent(
                status="ERROR",
                message="recording_storage_unavailable",
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
            "worker": self._worker(),
            "zlmediakit": self._zlm(),
            "storage": self._local_storage(
                targets
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
