"""Apply retention policies before camera recording policies."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session


from .config_import_support import ConfigurationApplyItem
from .config_import_retention import apply_retention_policies
from .config_import_recording_policies import apply_recording_policies


def apply_recording(
    service: type,
    session: Session,
    *,
    sections: dict[str, Any],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    camera_map: dict[str, uuid.UUID],
    group_map: dict[str, uuid.UUID],
    storage_map: dict[str, uuid.UUID],
    retention_map: dict[str, uuid.UUID],
    reconcile: set[uuid.UUID],
) -> None:
    retention = (
        sections.get(
            "recording",
            {},
        )
    )
    assert isinstance(retention, dict)
    apply_retention_policies(
        service, session, retention=retention, applied=applied,
        skipped=skipped, camera_map=camera_map, group_map=group_map,
        retention_map=retention_map,
    )

    recording_policies = (
        retention.get(
            "policies",
            [],
        )
    )
    assert isinstance(
        recording_policies,
        list,
    )
    apply_recording_policies(
        service, session, recording_policies=recording_policies,
        applied=applied, skipped=skipped, camera_map=camera_map,
        storage_map=storage_map, retention_map=retention_map,
        reconcile=reconcile,
    )
