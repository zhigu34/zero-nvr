"""Apply camera recording policies after resource IDs are mapped."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from .config_import_recording_dependencies import map_recording_dependencies
from .config_import_recording_policy_records import upsert_recording_policy
from .config_import_support import ConfigurationApplyItem


def apply_recording_policies(
    service: type,
    session: Session,
    *,
    recording_policies: list[dict[str, Any]],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    camera_map: dict[str, uuid.UUID],
    storage_map: dict[str, uuid.UUID],
    retention_map: dict[str, uuid.UUID],
    reconcile: set[uuid.UUID],
) -> None:
    for raw in recording_policies:
        assert isinstance(raw, dict)
        item = raw
        mapped = map_recording_dependencies(
            item, camera_map=camera_map, storage_map=storage_map,
            retention_map=retention_map,
        )
        if isinstance(mapped, str):
            skipped.append(
                service._apply_item(
                    section="recording",
                    resource_type="recording_policy",
                    item=item,
                    action="skipped",
                    reason=mapped,
                )
            )
            continue
        target_camera, target_storage, target_retention = mapped

        policy_changed = upsert_recording_policy(
            session, item=item, target_camera=target_camera,
            target_storage=target_storage, target_retention=target_retention,
        )
        if policy_changed:
            reconcile.add(
                target_camera
            )
        applied.append(
            service._apply_item(
                section="recording",
                resource_type=(
                    "recording_policy"
                ),
                item=item,
                action=(
                    "updated"
                    if policy_changed
                    else "matched"
                ),
                target_id=target_camera,
            )
        )
