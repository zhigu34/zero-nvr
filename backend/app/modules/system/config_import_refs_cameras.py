"""Validate cameras, streams, groups, and role camera scopes."""

from __future__ import annotations

from .config_import_document import ParsedSections
from .config_import_reference_ids import ReferenceIds
from .config_import_refs_groups import validate_group_references


def validate_cameras_references(service: type, parsed: ParsedSections, ids: ReferenceIds) -> None:
    cameras = parsed.cameras
    profiles = parsed.profiles
    bindings = parsed.bindings
    device_ids = ids.device_ids
    device_adapter_types = ids.device_adapter_types
    camera_ids = ids.camera_ids
    profile_ids = ids.profile_ids

    for index, item in enumerate(cameras):
        maintenance = item.get(
            "maintenance"
        )
        if (
            "maintenance" in item
            and not isinstance(
                maintenance,
                bool,
            )
        ):
            raise service._error(
                "configuration_import_invalid",
                "Camera maintenance state is invalid.",
                details={
                    "path": (
                        "$.sections.cameras.cameras"
                        f"[{index}].maintenance"
                    )
                },
            )
        mode = item.get(
            "time_sync_mode"
        )
        if (
            mode is not None
            and (
                not isinstance(mode, str)
                or mode not in {
                    "monitor",
                    "manage_ntp",
                    "ignore",
                }
            )
        ):
            raise service._error(
                "configuration_import_invalid",
                "Camera time synchronization mode is invalid.",
                details={
                    "path": (
                        "$.sections.cameras.cameras"
                        f"[{index}].time_sync_mode"
                    )
                },
            )
        device_id = service._require_ref(
            item.get("device_id"),
            device_ids,
            path=(
                "$.sections.cameras.cameras"
                f"[{index}].device_id"
            ),
            nullable=True,
        )
        if (
            mode is not None
            and mode != "ignore"
            and (
                device_id is None
                or device_adapter_types.get(
                    device_id
                )
                != "onvif"
            )
        ):
            raise service._error(
                "configuration_import_invalid",
                (
                    "Camera time synchronization mode "
                    "requires an ONVIF device."
                ),
                details={
                    "path": (
                        "$.sections.cameras.cameras"
                        f"[{index}].time_sync_mode"
                    )
                },
            )

    profile_camera: dict[str, str] = {}
    for index, item in enumerate(profiles):
        camera_id = service._require_ref(
            item.get("camera_id"),
            camera_ids,
            path=(
                "$.sections.cameras.stream_profiles"
                f"[{index}].camera_id"
            ),
        )
        assert camera_id is not None
        profile_camera[
            str(item["id"])
        ] = camera_id

    for index, item in enumerate(bindings):
        camera_id = service._require_ref(
            item.get("camera_id"),
            camera_ids,
            path=(
                "$.sections.cameras.stream_bindings"
                f"[{index}].camera_id"
            ),
        )
        profile_id = service._require_ref(
            item.get("stream_profile_id"),
            profile_ids,
            path=(
                "$.sections.cameras.stream_bindings"
                f"[{index}].stream_profile_id"
            ),
        )
        if (
            profile_id is not None
            and camera_id is not None
            and profile_camera.get(profile_id)
            != camera_id
        ):
            raise service._error(
                "configuration_import_reference_invalid",
                "Camera stream binding references a profile from another camera.",
                details={
                    "path": (
                        "$.sections.cameras.stream_bindings"
                        f"[{index}].stream_profile_id"
                    )
                },
            )

    validate_group_references(service, parsed, ids)
