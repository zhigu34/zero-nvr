"""Validate retention and recording references."""

from __future__ import annotations

from .config_import_document import ParsedSections
from .config_import_reference_ids import ReferenceIds


def validate_recording_references(service: type, parsed: ParsedSections, ids: ReferenceIds) -> None:
    retention_policies = parsed.retention_policies
    recording_policies = parsed.recording_policies
    camera_ids = ids.camera_ids
    group_ids = ids.group_ids
    storage_ids = ids.storage_ids
    retention_ids = ids.retention_ids
    role_ids = ids.role_ids

    for index, item in enumerate(
        retention_policies
    ):
        scope_type = item.get(
            "scope_type"
        )
        scope_id = item.get("scope_id")
        if scope_type == "GLOBAL":
            if scope_id is not None:
                raise service._error(
                    "configuration_import_reference_invalid",
                    "Global retention policy must not have a scope id.",
                    details={
                        "path": (
                            "$.sections.recording.retention_policies"
                            f"[{index}].scope_id"
                        )
                    },
                )
        elif scope_type == "CAMERA":
            service._require_ref(
                scope_id,
                camera_ids,
                path=(
                    "$.sections.recording.retention_policies"
                    f"[{index}].scope_id"
                ),
            )
        elif scope_type == "CAMERA_GROUP":
            service._require_ref(
                scope_id,
                group_ids,
                path=(
                    "$.sections.recording.retention_policies"
                    f"[{index}].scope_id"
                ),
            )
        else:
            raise service._error(
                "configuration_import_invalid",
                "Retention policy scope type is invalid.",
                details={
                    "path": (
                        "$.sections.recording.retention_policies"
                        f"[{index}].scope_type"
                    )
                },
            )

    for index, item in enumerate(
        recording_policies
    ):
        service._require_ref(
            item.get("camera_id"),
            camera_ids,
            path=(
                "$.sections.recording.policies"
                f"[{index}].camera_id"
            ),
        )
        service._require_ref(
            item.get("storage_target_id"),
            storage_ids,
            path=(
                "$.sections.recording.policies"
                f"[{index}].storage_target_id"
            ),
            nullable=True,
        )
        service._require_ref(
            item.get(
                "retention_policy_id"
            ),
            retention_ids,
            path=(
                "$.sections.recording.policies"
                f"[{index}].retention_policy_id"
            ),
            nullable=True,
        )

