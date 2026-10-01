"""Apply general and time settings from a configuration bundle."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings

from .config_import_support import ConfigurationApplyItem
from .settings import SystemSettingsService, TimeSystemSettingsService


def apply_general_time(
    session: Session,
    *,
    settings: Settings,
    sections: dict[str, Any],
    applied: list[ConfigurationApplyItem],
) -> None:
    general = sections.get(
        "general",
        {},
    )
    time_changes: dict[str, object] = {}
    if isinstance(general, dict) and general:
        general_changes = dict(general)
        legacy_timezone = general_changes.pop(
            "display_timezone",
            None,
        )
        legacy_servers = general_changes.pop(
            "camera_ntp_servers",
            None,
        )
        if general_changes:
            SystemSettingsService.update(
                session,
                settings=settings,
                changes=general_changes,
            )
        if legacy_timezone is not None:
            time_changes[
                "recording_timezone"
            ] = legacy_timezone
        if legacy_servers is not None:
            time_changes[
                "managed_camera_ntp_servers"
            ] = legacy_servers
            time_changes[
                "managed_camera_ntp_mode"
            ] = (
                "manual"
                if legacy_servers
                else "dhcp"
            )
        applied.append(
            ConfigurationApplyItem(
                section="general",
                resource_type="system_settings",
                source_id=None,
                target_id=None,
                name="General",
                action="updated",
            )
        )

    time_section = sections.get(
        "time",
        {},
    )
    if isinstance(time_section, dict):
        time_changes.update(
            dict(time_section)
        )
    if time_changes:
        TimeSystemSettingsService.update(
            session,
            changes=time_changes,
        )
        applied.append(
            ConfigurationApplyItem(
                section="time",
                resource_type="system_settings",
                source_id=None,
                target_id=None,
                name="Time",
                action="updated",
            )
        )
