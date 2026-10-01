"""Check cross-section references before applying a configuration bundle."""

from __future__ import annotations

from .config_import_document import ParsedSections
from .config_import_reference_ids import ReferenceIds
from .config_import_refs_devices import validate_devices_references
from .config_import_refs_cameras import validate_cameras_references
from .config_import_refs_recording import validate_recording_references
from .config_import_refs_integrations import validate_integrations_references


def validate_references(service: type, parsed: ParsedSections) -> None:
    roles = parsed.roles
    devices = parsed.devices
    endpoints = parsed.endpoints
    cameras = parsed.cameras
    profiles = parsed.profiles
    groups = parsed.groups
    storage_targets = parsed.storage_targets
    retention_policies = parsed.retention_policies
    notification_targets = parsed.notification_targets

    role_ids = service._id_set(
        roles,
        path="$.sections.roles",
    )
    device_ids = service._id_set(
        devices,
        path=(
            "$.sections.devices.devices"
        ),
    )
    device_adapter_types = {
        str(item["id"]): str(
            item.get(
                "adapter_type",
                "",
            )
        )
        for item in devices
    }

    endpoint_ids = service._id_set(
        endpoints,
        path=(
            "$.sections.devices.endpoints"
        ),
    )
    camera_ids = service._id_set(
        cameras,
        path=(
            "$.sections.cameras.cameras"
        ),
    )
    profile_ids = service._id_set(
        profiles,
        path=(
            "$.sections.cameras.stream_profiles"
        ),
    )
    group_ids = service._id_set(
        groups,
        path=(
            "$.sections.cameras.groups"
        ),
    )
    storage_ids = service._id_set(
        storage_targets,
        path=(
            "$.sections.storage_targets"
        ),
    )
    retention_ids = service._id_set(
        retention_policies,
        path=(
            "$.sections.recording.retention_policies"
        ),
    )
    notification_ids = service._id_set(
        notification_targets,
        path=(
            "$.sections.notification_targets"
        ),
    )

    ids = ReferenceIds(
        role_ids=role_ids,
        device_ids=device_ids,
        device_adapter_types=device_adapter_types,
        endpoint_ids=endpoint_ids,
        camera_ids=camera_ids,
        profile_ids=profile_ids,
        group_ids=group_ids,
        storage_ids=storage_ids,
        retention_ids=retention_ids,
        notification_ids=notification_ids,
    )
    validate_devices_references(service, parsed, ids)
    validate_cameras_references(service, parsed, ids)
    validate_recording_references(service, parsed, ids)
    validate_integrations_references(service, parsed, ids)
