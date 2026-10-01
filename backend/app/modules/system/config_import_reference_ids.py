"""Identifier sets collected before cross-section reference checks."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReferenceIds:
    role_ids: set[str]
    device_ids: set[str]
    device_adapter_types: dict[str, str]
    endpoint_ids: set[str]
    camera_ids: set[str]
    profile_ids: set[str]
    group_ids: set[str]
    storage_ids: set[str]
    retention_ids: set[str]
    notification_ids: set[str]
