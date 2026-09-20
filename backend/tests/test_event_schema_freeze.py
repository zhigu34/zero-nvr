from __future__ import annotations

from sqlalchemy import inspect

from app.modules.events.models import Event


def test_event_schema_matches_frozen_canonical_boundary() -> None:
    columns = {
        column.name
        for column in inspect(Event).columns
    }

    assert {
        "id",
        "source",
        "source_instance_id",
        "source_event_id",
        "camera_id",
        "category",
        "label",
        "started_at",
        "ended_at",
        "confidence",
        "severity",
        "zone",
        "snapshot_ref",
        "correlation_id",
        "metadata_json",
        "created_at",
        "updated_at",
    } == columns

    camera_fk = next(
        iter(inspect(Event).columns["camera_id"].foreign_keys)
    )
    assert camera_fk.ondelete == "RESTRICT"

    index_names = {
        index.name
        for index in inspect(Event).tables[0].indexes
    }
    assert {
        "uq_events_provider_identity",
        "ix_events_camera_started",
        "ix_events_source_started",
        "ix_events_category_started",
    } <= index_names


def test_event_module_does_not_promote_raw_provider_observations_to_tables() -> None:
    table_names = set(Event.metadata.tables)
    prohibited = {
        "detection_observations",
        "detection_observation",
        "event_fusion_groups",
        "event_fusion_members",
        "event_zone_intervals",
        "frigate_events",
        "raw_events",
    }
    assert prohibited.isdisjoint(table_names)
