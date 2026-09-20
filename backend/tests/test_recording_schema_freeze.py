from __future__ import annotations

from sqlalchemy import inspect

from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingProtection,
    RecordingSegment,
    RecordingTrigger,
    RetentionPolicy,
)
from app.modules.storage.models import RecordingLocation, StorageTarget


def column_names(model) -> set[str]:
    return {column.name for column in inspect(model).columns}


def foreign_key_ondelete(model, column_name: str) -> str | None:
    column = inspect(model).columns[column_name]
    foreign_key = next(iter(column.foreign_keys))
    return foreign_key.ondelete


def test_storage_target_matches_frozen_product_facts() -> None:
    columns = column_names(StorageTarget)

    assert {
        "id",
        "type",
        "role",
        "name",
        "enabled",
        "config_json",
        "credential_secret_ref",
        "created_at",
        "updated_at",
    } <= columns

    # Current capacity/health is runtime state and must not become periodic
    # business-table writes.
    assert {
        "kind",
        "health_state",
        "last_health_at",
        "last_error",
    }.isdisjoint(columns)


def test_recording_policy_keeps_baseline_and_event_axes_separate() -> None:
    columns = column_names(RecordingPolicy)

    assert {
        "baseline_mode",
        "schedule_json",
        "schedule_timezone",
        "event_recording_enabled",
        "event_filter_json",
        "segment_target_seconds",
        "pre_roll_seconds",
        "post_roll_seconds",
        "storage_target_id",
        "retention_policy_id",
        "enabled",
    } <= columns

    # EVENT_ONLY is represented by disabled baseline + enabled event recording,
    # not by a second monolithic mode state machine.
    assert "mode" not in columns


def test_recording_catalog_preserves_historical_facts() -> None:
    segment_columns = column_names(RecordingSegment)
    location_columns = column_names(RecordingLocation)

    assert "continuity_id" not in segment_columns
    assert "updated_at" not in segment_columns
    assert "recording_reasons_json" in segment_columns
    assert inspect(RecordingSegment).columns["stream_profile_id"].nullable is True

    assert foreign_key_ondelete(RecordingSegment, "camera_id") == "RESTRICT"
    assert foreign_key_ondelete(
        RecordingSegment,
        "stream_profile_id",
    ) == "SET NULL"
    assert foreign_key_ondelete(
        RecordingLocation,
        "recording_segment_id",
    ) == "RESTRICT"
    assert foreign_key_ondelete(
        RecordingLocation,
        "storage_target_id",
    ) == "RESTRICT"

    assert "deleted_at" in location_columns


def test_frozen_recording_entities_are_present() -> None:
    assert RecordingTrigger.__tablename__ == "recording_triggers"
    assert RetentionPolicy.__tablename__ == "retention_policies"
    assert RecordingProtection.__tablename__ == "recording_protections"
