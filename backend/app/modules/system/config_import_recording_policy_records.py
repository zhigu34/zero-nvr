"""Persist one imported recording policy and detect changed fields."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.recordings.models import RecordingPolicy
from app.modules.recordings.policy import RecordingPolicyService


def upsert_recording_policy(
    session: Session,
    *,
    item: dict[str, Any],
    target_camera: uuid.UUID,
    target_storage: uuid.UUID | None,
    target_retention: uuid.UUID | None,
) -> bool:
    policy_values = {
        "baseline_mode": str(item["baseline_mode"]),
        "schedule_json": dict(item.get("schedule") or {}),
        "schedule_timezone": item.get("schedule_timezone"),
        "event_recording_enabled": bool(item["event_recording_enabled"]),
        "event_filter_json": dict(item.get("event_filter") or {}),
        "segment_target_seconds": int(item["segment_target_seconds"]),
        "pre_roll_seconds": int(item["pre_roll_seconds"]),
        "post_roll_seconds": int(item["post_roll_seconds"]),
        "storage_target_id": target_storage,
        "retention_policy_id": target_retention,
        "enabled": bool(item["enabled"]),
    }
    existing_policy = session.scalar(
        select(RecordingPolicy).where(RecordingPolicy.camera_id == target_camera)
    )
    policy_changed = (
        existing_policy is None
        or any(
            getattr(existing_policy, key) != value
            for key, value in policy_values.items()
        )
    )
    RecordingPolicyService.put(
        session, camera_id=target_camera, values=policy_values
    )
    return policy_changed
