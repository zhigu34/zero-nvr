"""Read the configuration envelope and section shapes in export order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings

from .config_import_envelope import read_envelope_sections
from .config_import_section_groups import (
    read_camera_items,
    read_device_items,
    read_recording_items,
)
from .settings import TimeSystemSettingsService


@dataclass(frozen=True, slots=True)
class ParsedSections:
    general: dict[str, Any]
    time_settings: dict[str, Any]
    roles: list[dict[str, Any]]
    devices: list[dict[str, Any]]
    endpoints: list[dict[str, Any]]
    device_credentials: list[dict[str, Any]]
    cameras: list[dict[str, Any]]
    profiles: list[dict[str, Any]]
    bindings: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    members: list[dict[str, Any]]
    recording_policies: list[dict[str, Any]]
    retention_policies: list[dict[str, Any]]
    storage_targets: list[dict[str, Any]]
    alert_policies: list[dict[str, Any]]
    notification_targets: list[dict[str, Any]]
    frigate: dict[str, Any] | None
    backup_policies: list[dict[str, Any]]


def parse_bundle(
    service: type,
    bundle: dict[str, Any],
    *,
    settings: Settings,
) -> ParsedSections:
    sections = read_envelope_sections(service, bundle)

    general = service._mapping(
        sections.get("general", {}),
        path="$.sections.general",
    )
    time_settings = service._mapping(
        sections.get("time", {}),
        path="$.sections.time",
    )
    if time_settings:
        TimeSystemSettingsService.normalize(
            current=None,
            legacy=None,
            changes=dict(time_settings),
        )
    roles = service._items(
        sections.get("roles", []),
        path="$.sections.roles",
    )
    devices, endpoints, device_credentials = read_device_items(service, sections)
    cameras, profiles, bindings, groups, members = read_camera_items(service, sections)
    recording_policies, retention_policies = read_recording_items(service, sections)
    storage_targets = service._items(
        sections.get(
            "storage_targets",
            [],
        ),
        path=(
            "$.sections.storage_targets"
        ),
    )
    alert_policies = service._items(
        sections.get(
            "alert_policies",
            [],
        ),
        path=(
            "$.sections.alert_policies"
        ),
    )
    notification_targets = service._items(
        sections.get(
            "notification_targets",
            [],
        ),
        path=(
            "$.sections.notification_targets"
        ),
    )
    frigate = sections.get("frigate")
    if (
        frigate is not None
        and not isinstance(frigate, dict)
    ):
        raise service._error(
            "configuration_import_invalid",
            "Frigate configuration must be an object or null.",
            details={
                "path": "$.sections.frigate"
            },
        )
    backup_policies = service._items(
        sections.get(
            "backup_policies",
            [],
        ),
        path=(
            "$.sections.backup_policies"
        ),
    )
    return ParsedSections(
        general=general,
        time_settings=time_settings,
        roles=roles,
        devices=devices,
        endpoints=endpoints,
        device_credentials=device_credentials,
        cameras=cameras,
        profiles=profiles,
        bindings=bindings,
        groups=groups,
        members=members,
        recording_policies=recording_policies,
        retention_policies=retention_policies,
        storage_targets=storage_targets,
        alert_policies=alert_policies,
        notification_targets=notification_targets,
        frigate=frigate,
        backup_policies=backup_policies,
    )
