"""Build preflight counts, credential requirements, and warnings."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings

from .config_import_document import ParsedSections
from .config_import_support import ConfigurationValidation
from .config_import_credentials import collect_credential_requirements


def summarize_bundle(
    service: type,
    parsed: ParsedSections,
    bundle: dict[str, Any],
    *,
    settings: Settings,
) -> ConfigurationValidation:
    general = parsed.general
    time_settings = parsed.time_settings
    roles = parsed.roles
    devices = parsed.devices
    endpoints = parsed.endpoints
    device_credentials = parsed.device_credentials
    cameras = parsed.cameras
    profiles = parsed.profiles
    bindings = parsed.bindings
    groups = parsed.groups
    members = parsed.members
    recording_policies = parsed.recording_policies
    retention_policies = parsed.retention_policies
    storage_targets = parsed.storage_targets
    alert_policies = parsed.alert_policies
    notification_targets = parsed.notification_targets
    frigate = parsed.frigate
    backup_policies = parsed.backup_policies

    requirements = collect_credential_requirements(service, parsed)

    section_counts = {
        "general": 1 if general else 0,
        "time": 1 if time_settings else 0,
        "roles": len(roles),
        "devices": (
            len(devices)
            + len(endpoints)
            + len(device_credentials)
        ),
        "cameras": (
            len(cameras)
            + len(profiles)
            + len(bindings)
            + len(groups)
            + len(members)
        ),
        "recording": (
            len(recording_policies)
            + len(retention_policies)
        ),
        "storage_targets": (
            len(storage_targets)
        ),
        "alert_policies": (
            len(alert_policies)
        ),
        "notification_targets": (
            len(notification_targets)
        ),
        "frigate": (
            1
            if isinstance(frigate, dict)
            else 0
        ),
        "backup_policies": (
            len(backup_policies)
        ),
    }

    source_version = bundle.get(
        "application_version"
    )
    if source_version is not None:
        source_version = str(
            source_version
        )

    warnings = [
        (
            "Users, sessions, API tokens, audit history, "
            "event history, recording catalog and secret "
            "material are intentionally not part of "
            "configuration import."
        )
    ]
    if requirements:
        warnings.append(
            (
                f"{len(requirements)} credential input(s) "
                "must be supplied separately after import."
            )
        )
    if (
        source_version
        and source_version
        != settings.app_version
    ):
        warnings.append(
            (
                "Configuration was exported by zero-nvr "
                f"{source_version}; this system is "
                f"{settings.app_version}."
            )
        )

    return ConfigurationValidation(
        source_application_version=(
            source_version
        ),
        section_counts=section_counts,
        credentials_required=tuple(
            requirements
        ),
        warnings=tuple(warnings),
    )
