from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError

from .models import SystemSetting


_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


@dataclass(frozen=True, slots=True)
class GeneralSystemSettings:
    system_name: str
    display_timezone: str
    camera_ntp_servers: tuple[str, ...]


class SystemSettingsService:
    namespace = "general"

    @staticmethod
    def _ntp_server(value: str) -> str:
        item = value.strip()
        if (
            not item
            or len(item) > 253
            or any(ch in item for ch in "/\\?#@ ")
        ):
            raise ApiError(
                status_code=400,
                code="system_ntp_server_invalid",
                message="Camera NTP server is invalid.",
            )
        try:
            return str(ipaddress.ip_address(item))
        except ValueError:
            if not _HOSTNAME.fullmatch(item):
                raise ApiError(
                    status_code=400,
                    code="system_ntp_server_invalid",
                    message="Camera NTP server is invalid.",
                )
            return item.lower()

    @classmethod
    def normalize(
        cls,
        *,
        settings: Settings,
        current: dict[str, object] | None,
        changes: dict[str, object],
    ) -> dict[str, object]:
        base = {
            "system_name": settings.app_name,
            "display_timezone": "UTC",
            "camera_ntp_servers": [],
        }
        if current:
            base.update(current)

        if "system_name" in changes:
            raw = changes["system_name"]
            if (
                not isinstance(raw, str)
                or not raw.strip()
                or len(raw.strip()) > 128
            ):
                raise ApiError(
                    status_code=400,
                    code="system_name_invalid",
                    message="System name is invalid.",
                )
            base["system_name"] = raw.strip()

        if "display_timezone" in changes:
            raw = changes["display_timezone"]
            if not isinstance(raw, str) or not raw.strip():
                raise ApiError(
                    status_code=400,
                    code="system_timezone_invalid",
                    message="Display timezone is invalid.",
                )
            timezone = raw.strip()
            try:
                ZoneInfo(timezone)
            except ZoneInfoNotFoundError as exc:
                raise ApiError(
                    status_code=400,
                    code="system_timezone_invalid",
                    message="Display timezone is invalid.",
                ) from exc
            base["display_timezone"] = timezone

        if "camera_ntp_servers" in changes:
            raw = changes["camera_ntp_servers"]
            if (
                not isinstance(raw, list)
                or len(raw) > 4
                or not all(
                    isinstance(item, str)
                    for item in raw
                )
            ):
                raise ApiError(
                    status_code=400,
                    code="system_ntp_servers_invalid",
                    message="Camera NTP servers are invalid.",
                )
            normalized: list[str] = []
            for item in raw:
                value = cls._ntp_server(item)
                if value not in normalized:
                    normalized.append(value)
            base["camera_ntp_servers"] = normalized

        return base

    @classmethod
    def get(
        cls,
        session: Session,
        *,
        settings: Settings,
    ) -> GeneralSystemSettings:
        row = session.get(
            SystemSetting,
            cls.namespace,
        )
        value = cls.normalize(
            settings=settings,
            current=(
                row.value_json
                if row is not None
                else None
            ),
            changes={},
        )
        return GeneralSystemSettings(
            system_name=str(value["system_name"]),
            display_timezone=str(
                value["display_timezone"]
            ),
            camera_ntp_servers=tuple(
                str(item)
                for item in value[
                    "camera_ntp_servers"
                ]
            ),
        )

    @classmethod
    def update(
        cls,
        session: Session,
        *,
        settings: Settings,
        changes: dict[str, object],
    ) -> GeneralSystemSettings:
        row = session.get(
            SystemSetting,
            cls.namespace,
        )
        normalized = cls.normalize(
            settings=settings,
            current=(
                row.value_json
                if row is not None
                else None
            ),
            changes=changes,
        )
        if row is None:
            row = SystemSetting(
                namespace=cls.namespace,
                value_json=normalized,
            )
            session.add(row)
        else:
            row.value_json = normalized
        session.flush()
        return cls.get(
            session,
            settings=settings,
        )


@dataclass(frozen=True, slots=True)
class TimeSystemSettings:
    recording_timezone: str
    managed_camera_ntp_mode: Literal["manual", "dhcp"]
    managed_camera_ntp_servers: tuple[str, ...]


class TimeSystemSettingsService:
    namespace = "time"

    @staticmethod
    def _timezone(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ApiError(
                status_code=400,
                code="system_timezone_invalid",
                message="Recording timezone is invalid.",
            )
        timezone = value.strip()
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ApiError(
                status_code=400,
                code="system_timezone_invalid",
                message="Recording timezone is invalid.",
            ) from exc
        return timezone

    @classmethod
    def _servers(
        cls,
        value: object,
    ) -> list[str]:
        if (
            not isinstance(value, list)
            or len(value) > 4
            or not all(
                isinstance(item, str)
                for item in value
            )
        ):
            raise ApiError(
                status_code=400,
                code="system_ntp_servers_invalid",
                message="Managed camera NTP servers are invalid.",
            )
        normalized: list[str] = []
        for item in value:
            server = SystemSettingsService._ntp_server(
                item
            )
            if server not in normalized:
                normalized.append(server)
        return normalized

    @staticmethod
    def _legacy(
        session: Session,
    ) -> dict[str, object]:
        row = session.get(
            SystemSetting,
            SystemSettingsService.namespace,
        )
        if row is None:
            return {}
        value = row.value_json or {}
        result: dict[str, object] = {}
        timezone = value.get("display_timezone")
        if isinstance(timezone, str) and timezone.strip():
            result["recording_timezone"] = timezone
        servers = value.get("camera_ntp_servers")
        if (
            isinstance(servers, list)
            and all(
                isinstance(item, str)
                for item in servers
            )
        ):
            result["managed_camera_ntp_servers"] = list(
                servers
            )
            result["managed_camera_ntp_mode"] = (
                "manual" if servers else "dhcp"
            )
        return result

    @classmethod
    def normalize(
        cls,
        *,
        current: dict[str, object] | None,
        legacy: dict[str, object] | None,
        changes: dict[str, object],
    ) -> dict[str, object]:
        base: dict[str, object] = {
            "recording_timezone": "UTC",
            "managed_camera_ntp_mode": "dhcp",
            "managed_camera_ntp_servers": [],
        }
        if legacy:
            base.update(legacy)
        if current:
            base.update(current)
        base.update(changes)

        timezone = cls._timezone(
            base["recording_timezone"]
        )
        mode = base["managed_camera_ntp_mode"]
        if mode not in {"manual", "dhcp"}:
            raise ApiError(
                status_code=400,
                code="system_ntp_mode_invalid",
                message=(
                    "Managed camera NTP mode must be "
                    "manual or dhcp."
                ),
            )
        servers = cls._servers(
            base["managed_camera_ntp_servers"]
        )
        if mode == "manual" and not servers:
            raise ApiError(
                status_code=400,
                code="system_ntp_servers_required",
                message=(
                    "Manual managed camera NTP mode "
                    "requires at least one server."
                ),
            )

        return {
            "recording_timezone": timezone,
            "managed_camera_ntp_mode": mode,
            "managed_camera_ntp_servers": servers,
        }

    @classmethod
    def get(
        cls,
        session: Session,
    ) -> TimeSystemSettings:
        row = session.get(
            SystemSetting,
            cls.namespace,
        )
        value = cls.normalize(
            current=(
                row.value_json
                if row is not None
                else None
            ),
            legacy=(
                cls._legacy(session)
                if row is None
                else None
            ),
            changes={},
        )
        return TimeSystemSettings(
            recording_timezone=str(
                value["recording_timezone"]
            ),
            managed_camera_ntp_mode=value[
                "managed_camera_ntp_mode"
            ],
            managed_camera_ntp_servers=tuple(
                str(item)
                for item in value[
                    "managed_camera_ntp_servers"
                ]
            ),
        )

    @classmethod
    def update(
        cls,
        session: Session,
        *,
        changes: dict[str, object],
    ) -> TimeSystemSettings:
        row = session.get(
            SystemSetting,
            cls.namespace,
        )
        normalized = cls.normalize(
            current=(
                row.value_json
                if row is not None
                else None
            ),
            legacy=(
                cls._legacy(session)
                if row is None
                else None
            ),
            changes=changes,
        )
        if row is None:
            row = SystemSetting(
                namespace=cls.namespace,
                value_json=normalized,
            )
            session.add(row)
        else:
            row.value_json = normalized
        session.flush()
        return cls.get(session)


@dataclass(frozen=True, slots=True)
class RuntimeTuningSettings:
    prebuffer_fragment_seconds: int
    prebuffer_buffer_seconds: int
    turn_credential_ttl_seconds: int
    playback_cache_max_bytes: int
    playback_cache_ttl_seconds: int
    playback_restore_lock_ttl_seconds: int
    live_transcode_max_derivatives: int
    live_transcode_idle_ttl_seconds: int
    live_transcode_lease_ttl_seconds: int
    live_transcode_startup_timeout_seconds: float
    live_transcode_cpu_threads: int
    live_transcode_video_bitrate_kbps: int


class RuntimeTuningSettingsService:
    namespace = "runtime_tuning"

    @staticmethod
    def _bounded_int(
        value: object,
        *,
        minimum: int,
        maximum: int,
        code: str,
        field: str,
    ) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < minimum
            or value > maximum
        ):
            raise ApiError(
                status_code=400,
                code=code,
                message=(
                    f"{field} must be between "
                    f"{minimum} and {maximum}."
                ),
            )
        return value

    @staticmethod
    def _bounded_float(
        value: object,
        *,
        minimum: float,
        maximum: float,
        code: str,
        field: str,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            raise ApiError(
                status_code=400,
                code=code,
                message=(
                    f"{field} must be between "
                    f"{minimum:g} and {maximum:g}."
                ),
            )
        normalized = float(value)
        if normalized < minimum or normalized > maximum:
            raise ApiError(
                status_code=400,
                code=code,
                message=(
                    f"{field} must be between "
                    f"{minimum:g} and {maximum:g}."
                ),
            )
        return normalized

    @classmethod
    def defaults(
        cls,
        settings: Settings,
    ) -> RuntimeTuningSettings:
        return RuntimeTuningSettings(
            prebuffer_fragment_seconds=(
                settings.prebuffer_fragment_seconds
            ),
            prebuffer_buffer_seconds=(
                settings.prebuffer_buffer_seconds
            ),
            turn_credential_ttl_seconds=(
                settings.turn_credential_ttl_seconds
            ),
            playback_cache_max_bytes=(
                settings.playback_cache_max_bytes
            ),
            playback_cache_ttl_seconds=(
                settings.playback_cache_ttl_seconds
            ),
            playback_restore_lock_ttl_seconds=(
                settings.playback_restore_lock_ttl_seconds
            ),
            live_transcode_max_derivatives=(
                settings.live_transcode_max_derivatives
            ),
            live_transcode_idle_ttl_seconds=(
                settings.live_transcode_idle_ttl_seconds
            ),
            live_transcode_lease_ttl_seconds=(
                settings.live_transcode_lease_ttl_seconds
            ),
            live_transcode_startup_timeout_seconds=(
                settings.live_transcode_startup_timeout_seconds
            ),
            live_transcode_cpu_threads=(
                settings.live_transcode_cpu_threads
            ),
            live_transcode_video_bitrate_kbps=(
                settings.live_transcode_video_bitrate_kbps
            ),
        )

    @classmethod
    def normalize(
        cls,
        *,
        settings: Settings,
        current: dict[str, object] | None,
        changes: dict[str, object],
    ) -> dict[str, object]:
        defaults = cls.defaults(settings)
        base: dict[str, object] = {
            "prebuffer_fragment_seconds": (
                defaults.prebuffer_fragment_seconds
            ),
            "prebuffer_buffer_seconds": (
                defaults.prebuffer_buffer_seconds
            ),
            "turn_credential_ttl_seconds": (
                defaults.turn_credential_ttl_seconds
            ),
            "playback_cache_max_bytes": defaults.playback_cache_max_bytes,
            "playback_cache_ttl_seconds": defaults.playback_cache_ttl_seconds,
            "playback_restore_lock_ttl_seconds": (
                defaults.playback_restore_lock_ttl_seconds
            ),
            "live_transcode_max_derivatives": (
                defaults.live_transcode_max_derivatives
            ),
            "live_transcode_idle_ttl_seconds": (
                defaults.live_transcode_idle_ttl_seconds
            ),
            "live_transcode_lease_ttl_seconds": (
                defaults.live_transcode_lease_ttl_seconds
            ),
            "live_transcode_startup_timeout_seconds": (
                defaults.live_transcode_startup_timeout_seconds
            ),
            "live_transcode_cpu_threads": (
                defaults.live_transcode_cpu_threads
            ),
            "live_transcode_video_bitrate_kbps": (
                defaults.live_transcode_video_bitrate_kbps
            ),
        }
        if current:
            base.update(current)
        base.update(changes)

        return {
            "prebuffer_fragment_seconds": cls._bounded_int(
                base["prebuffer_fragment_seconds"],
                minimum=2,
                maximum=30,
                code="runtime_prebuffer_fragment_seconds_invalid",
                field="Prebuffer fragment seconds",
            ),
            "prebuffer_buffer_seconds": cls._bounded_int(
                base["prebuffer_buffer_seconds"],
                minimum=10,
                maximum=600,
                code="runtime_prebuffer_buffer_seconds_invalid",
                field="Prebuffer buffer seconds",
            ),
            "turn_credential_ttl_seconds": cls._bounded_int(
                base["turn_credential_ttl_seconds"],
                minimum=60,
                maximum=3600,
                code="runtime_turn_credential_ttl_invalid",
                field="TURN credential TTL",
            ),
            "playback_cache_max_bytes": cls._bounded_int(
                base["playback_cache_max_bytes"],
                minimum=64 * 1024 * 1024,
                maximum=1024 * 1024 * 1024 * 1024,
                code="runtime_playback_cache_max_bytes_invalid",
                field="Playback cache size",
            ),
            "playback_cache_ttl_seconds": cls._bounded_int(
                base["playback_cache_ttl_seconds"],
                minimum=60,
                maximum=7 * 24 * 60 * 60,
                code="runtime_playback_cache_ttl_invalid",
                field="Playback cache TTL",
            ),
            "playback_restore_lock_ttl_seconds": cls._bounded_int(
                base["playback_restore_lock_ttl_seconds"],
                minimum=60,
                maximum=7 * 24 * 60 * 60,
                code="runtime_playback_restore_lock_ttl_invalid",
                field="Playback restore lock TTL",
            ),
            "live_transcode_max_derivatives": cls._bounded_int(
                base["live_transcode_max_derivatives"],
                minimum=1,
                maximum=8,
                code="runtime_live_transcode_capacity_invalid",
                field="Live transcode derivative limit",
            ),
            "live_transcode_idle_ttl_seconds": cls._bounded_int(
                base["live_transcode_idle_ttl_seconds"],
                minimum=5,
                maximum=300,
                code="runtime_live_transcode_idle_ttl_invalid",
                field="Live transcode idle TTL",
            ),
            "live_transcode_lease_ttl_seconds": cls._bounded_int(
                base["live_transcode_lease_ttl_seconds"],
                minimum=15,
                maximum=300,
                code="runtime_live_transcode_lease_ttl_invalid",
                field="Live transcode lease TTL",
            ),
            "live_transcode_startup_timeout_seconds": cls._bounded_float(
                base["live_transcode_startup_timeout_seconds"],
                minimum=1,
                maximum=30,
                code="runtime_live_transcode_startup_timeout_invalid",
                field="Live transcode startup timeout",
            ),
            "live_transcode_cpu_threads": cls._bounded_int(
                base["live_transcode_cpu_threads"],
                minimum=1,
                maximum=8,
                code="runtime_live_transcode_cpu_threads_invalid",
                field="Live transcode CPU threads",
            ),
            "live_transcode_video_bitrate_kbps": cls._bounded_int(
                base["live_transcode_video_bitrate_kbps"],
                minimum=512,
                maximum=20000,
                code="runtime_live_transcode_bitrate_invalid",
                field="Live transcode bitrate",
            ),
        }

    @classmethod
    def get(
        cls,
        session: Session,
        *,
        settings: Settings,
    ) -> RuntimeTuningSettings:
        row = session.get(SystemSetting, cls.namespace)
        value = cls.normalize(
            settings=settings,
            current=row.value_json if row is not None else None,
            changes={},
        )
        return RuntimeTuningSettings(
            prebuffer_fragment_seconds=int(
                value["prebuffer_fragment_seconds"]
            ),
            prebuffer_buffer_seconds=int(
                value["prebuffer_buffer_seconds"]
            ),
            turn_credential_ttl_seconds=int(
                value["turn_credential_ttl_seconds"]
            ),
            playback_cache_max_bytes=int(value["playback_cache_max_bytes"]),
            playback_cache_ttl_seconds=int(value["playback_cache_ttl_seconds"]),
            playback_restore_lock_ttl_seconds=int(
                value["playback_restore_lock_ttl_seconds"]
            ),
            live_transcode_max_derivatives=int(
                value["live_transcode_max_derivatives"]
            ),
            live_transcode_idle_ttl_seconds=int(
                value["live_transcode_idle_ttl_seconds"]
            ),
            live_transcode_lease_ttl_seconds=int(
                value["live_transcode_lease_ttl_seconds"]
            ),
            live_transcode_startup_timeout_seconds=float(
                value["live_transcode_startup_timeout_seconds"]
            ),
            live_transcode_cpu_threads=int(
                value["live_transcode_cpu_threads"]
            ),
            live_transcode_video_bitrate_kbps=int(
                value["live_transcode_video_bitrate_kbps"]
            ),
        )

    @classmethod
    def update(
        cls,
        session: Session,
        *,
        settings: Settings,
        changes: dict[str, object],
    ) -> RuntimeTuningSettings:
        row = session.get(SystemSetting, cls.namespace)
        normalized = cls.normalize(
            settings=settings,
            current=row.value_json if row is not None else None,
            changes=changes,
        )
        if row is None:
            row = SystemSetting(
                namespace=cls.namespace,
                value_json=normalized,
            )
            session.add(row)
        else:
            row.value_json = normalized
        session.flush()
        return cls.get(session, settings=settings)

