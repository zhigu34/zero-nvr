"""Collect credentials that must be supplied locally after import."""

from __future__ import annotations

from .config_import_document import ParsedSections
from .config_import_support import CredentialRequirement


def collect_credential_requirements(
    service: type,
    parsed: ParsedSections,
) -> list[CredentialRequirement]:
    device_credentials = parsed.device_credentials
    profiles = parsed.profiles
    storage_targets = parsed.storage_targets
    notification_targets = parsed.notification_targets
    oidc_providers = parsed.oidc_providers
    frigate = parsed.frigate
    backup_policies = parsed.backup_policies
    requirements: list[
        CredentialRequirement
    ] = []
    for item in device_credentials:
        if item.get(
            "credentials_configured"
        ) is True:
            service._requirement(
                requirements,
                section="devices",
                resource_type="device_credential",
                item=item,
                credential=str(
                    item.get("kind")
                    or "device"
                ),
            )
    for item in profiles:
        if item.get(
            "stream_uri_configured"
        ) is True:
            service._requirement(
                requirements,
                section="cameras",
                resource_type="camera_stream_profile",
                item=item,
                credential="stream_uri",
            )
    for item in storage_targets:
        if item.get(
            "credentials_configured"
        ) is True:
            service._requirement(
                requirements,
                section="storage_targets",
                resource_type="storage_target",
                item=item,
                credential="rclone_config",
            )
    for item in notification_targets:
        if item.get(
            "url_configured"
        ) is True:
            service._requirement(
                requirements,
                section="notification_targets",
                resource_type="notification_target",
                item=item,
                credential="apprise_url",
            )
        if item.get(
            "credentials_configured"
        ) is True:
            service._requirement(
                requirements,
                section="notification_targets",
                resource_type="notification_target",
                item=item,
                credential="smtp_credentials",
            )
    for item in oidc_providers:
        if item.get(
            "client_secret_configured"
        ) is True:
            service._requirement(
                requirements,
                section="oidc_providers",
                resource_type="oidc_provider",
                item=item,
                credential="client_secret",
            )
    if (
        isinstance(frigate, dict)
        and frigate.get(
            "credentials_configured"
        ) is True
    ):
        service._requirement(
            requirements,
            section="frigate",
            resource_type="frigate_provider",
            item={
                "id": None,
                "name": "Frigate",
            },
            credential="integration_credentials",
        )
    for item in backup_policies:
        if item.get(
            "repository_configured"
        ) is True:
            service._requirement(
                requirements,
                section="backup_policies",
                resource_type="backup_policy",
                item=item,
                credential="repository",
            )
        if item.get(
            "credentials_configured"
        ) is True:
            service._requirement(
                requirements,
                section="backup_policies",
                resource_type="backup_policy",
                item=item,
                credential="repository_credentials",
            )

    return requirements
