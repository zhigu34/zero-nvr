from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
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
