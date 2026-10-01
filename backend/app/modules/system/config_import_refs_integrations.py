"""Validate Frigate and alert policy references."""

from __future__ import annotations

from .config_import_document import ParsedSections
from .config_import_reference_ids import ReferenceIds


def validate_integrations_references(service: type, parsed: ParsedSections, ids: ReferenceIds) -> None:
    frigate = parsed.frigate
    alert_policies = parsed.alert_policies
    camera_ids = ids.camera_ids
    notification_ids = ids.notification_ids

    if isinstance(frigate, dict):
        camera_map = frigate.get(
            "camera_map",
            {},
        )
        if not isinstance(camera_map, dict):
            raise service._error(
                "configuration_import_invalid",
                "Frigate camera map must be an object.",
                details={
                    "path": (
                        "$.sections.frigate.camera_map"
                    )
                },
            )
        for key, camera_id in camera_map.items():
            service._require_ref(
                camera_id,
                camera_ids,
                path=(
                    "$.sections.frigate.camera_map."
                    + str(key)
                ),
            )

    for index, item in enumerate(
        alert_policies
    ):
        match = item.get("match", {})
        action = item.get("action", {})
        if not isinstance(match, dict):
            raise service._error(
                "configuration_import_invalid",
                "Alert match configuration must be an object.",
                details={
                    "path": (
                        "$.sections.alert_policies"
                        f"[{index}].match"
                    )
                },
            )
        if not isinstance(action, dict):
            raise service._error(
                "configuration_import_invalid",
                "Alert action configuration must be an object.",
                details={
                    "path": (
                        "$.sections.alert_policies"
                        f"[{index}].action"
                    )
                },
            )
        for camera_index, camera_id in enumerate(
            match.get("camera_ids", [])
        ):
            service._require_ref(
                camera_id,
                camera_ids,
                path=(
                    "$.sections.alert_policies"
                    f"[{index}].match.camera_ids"
                    f"[{camera_index}]"
                ),
            )
        for target_index, target_id in enumerate(
            action.get(
                "notification_target_ids",
                [],
            )
        ):
            service._require_ref(
                target_id,
                notification_ids,
                path=(
                    "$.sections.alert_policies"
                    f"[{index}].action.notification_target_ids"
                    f"[{target_index}]"
                ),
            )
