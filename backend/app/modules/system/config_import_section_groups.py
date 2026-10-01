"""Read nested device, camera, and recording resources in export order."""

from __future__ import annotations

from typing import Any


def read_device_items(
    service: type, sections: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    devices_section = service._mapping(
        sections.get("devices", {}),
        path="$.sections.devices",
    )
    devices = service._items(
        devices_section.get("devices", []),
        path="$.sections.devices.devices",
    )
    endpoints = service._items(
        devices_section.get("endpoints", []),
        path="$.sections.devices.endpoints",
    )
    credentials = service._items(
        devices_section.get("credentials", []),
        path="$.sections.devices.credentials",
    )
    return devices, endpoints, credentials


def read_camera_items(
    service: type, sections: dict[str, Any]
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    cameras_section = service._mapping(
        sections.get("cameras", {}),
        path="$.sections.cameras",
    )
    cameras = service._items(
        cameras_section.get("cameras", []),
        path="$.sections.cameras.cameras",
    )
    profiles = service._items(
        cameras_section.get("stream_profiles", []),
        path="$.sections.cameras.stream_profiles",
    )
    bindings = service._items(
        cameras_section.get("stream_bindings", []),
        path="$.sections.cameras.stream_bindings",
    )
    groups = service._items(
        cameras_section.get("groups", []),
        path="$.sections.cameras.groups",
    )
    members = service._items(
        cameras_section.get("group_members", []),
        path="$.sections.cameras.group_members",
    )
    return cameras, profiles, bindings, groups, members


def read_recording_items(
    service: type, sections: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    recording_section = service._mapping(
        sections.get("recording", {}),
        path="$.sections.recording",
    )
    policies = service._items(
        recording_section.get("policies", []),
        path="$.sections.recording.policies",
    )
    retention_policies = service._items(
        recording_section.get("retention_policies", []),
        path="$.sections.recording.retention_policies",
    )
    return policies, retention_policies
