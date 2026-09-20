"""recording catalog, policies, triggers, and storage targets

Revision ID: 0004_recording_catalog
Revises: 0003_camera_inventory
Create Date: 2026-09-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_recording_catalog"
down_revision: str | Sequence[str] | None = "0003_camera_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storage_targets",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("health_state", sa.String(length=32), nullable=False),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('LOCAL_RECORDING','RCLONE_ARCHIVE','PLAYBACK_CACHE','BACKUP')",
            name="ck_storage_targets_storage_target_kind",
        ),
        sa.CheckConstraint(
            "health_state IN ('UNKNOWN','OK','PRESSURE','CRITICAL','OFFLINE','READ_ONLY')",
            name="ck_storage_targets_storage_target_health_state",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storage_targets"),
        sa.UniqueConstraint("name", name="uq_storage_targets_name"),
    )

    op.create_table(
        "recording_policies",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("storage_target_id", sa.Uuid(), nullable=True),
        sa.Column("segment_target_seconds", sa.Integer(), nullable=False),
        sa.Column("pre_roll_seconds", sa.Integer(), nullable=False),
        sa.Column("post_roll_seconds", sa.Integer(), nullable=False),
        sa.Column("schedule_timezone", sa.String(length=128), nullable=True),
        sa.Column("schedule", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mode IN ('CONTINUOUS','SCHEDULE','EVENT_ONLY','DISABLED')",
            name="ck_recording_policies_recording_policy_mode",
        ),
        sa.CheckConstraint(
            "segment_target_seconds > 0",
            name="ck_recording_policies_recording_policy_segment_target_positive",
        ),
        sa.CheckConstraint(
            "pre_roll_seconds >= 0",
            name="ck_recording_policies_recording_policy_pre_roll_nonnegative",
        ),
        sa.CheckConstraint(
            "post_roll_seconds >= 0",
            name="ck_recording_policies_recording_policy_post_roll_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_recording_policies_camera_id_cameras",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["storage_target_id"],
            ["storage_targets.id"],
            name="fk_recording_policies_storage_target_id_storage_targets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_policies"),
        sa.UniqueConstraint(
            "camera_id",
            name="uq_recording_policies_camera_id",
        ),
    )

    op.create_table(
        "recording_triggers",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_event_id", sa.String(length=512), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pre_roll_seconds", sa.Integer(), nullable=False),
        sa.Column("post_roll_seconds", sa.Integer(), nullable=False),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('PENDING','ACTIVE','COMPLETED','CANCELLED','FAILED')",
            name="ck_recording_triggers_recording_trigger_state",
        ),
        sa.CheckConstraint(
            "pre_roll_seconds >= 0",
            name="ck_recording_triggers_recording_trigger_pre_roll_nonnegative",
        ),
        sa.CheckConstraint(
            "post_roll_seconds >= 0",
            name="ck_recording_triggers_recording_trigger_post_roll_nonnegative",
        ),
        sa.CheckConstraint(
            "planned_end_at >= planned_start_at",
            name="ck_recording_triggers_recording_trigger_window",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_recording_triggers_camera_id_cameras",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_triggers"),
    )
    op.create_index(
        "uq_recording_triggers_source_event",
        "recording_triggers",
        ["camera_id", "source", "source_event_id"],
        unique=True,
        sqlite_where=sa.text("source_event_id IS NOT NULL"),
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )
    op.create_index(
        "ix_recording_triggers_camera_state_end",
        "recording_triggers",
        ["camera_id", "state", "planned_end_at"],
        unique=False,
    )

    op.create_table(
        "recording_segments",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("stream_profile_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("recording_reasons", sa.JSON(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("codec", sa.String(length=32), nullable=True),
        sa.Column("container", sa.String(length=32), nullable=False),
        sa.Column("source_media_server_id", sa.String(length=128), nullable=False),
        sa.Column("source_app", sa.String(length=128), nullable=False),
        sa.Column("source_stream", sa.String(length=256), nullable=False),
        sa.Column("integrity_status", sa.String(length=32), nullable=False),
        sa.Column("completion_reason", sa.String(length=64), nullable=False),
        sa.Column("timing_status", sa.String(length=32), nullable=False),
        sa.Column("timing_source", sa.String(length=64), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ended_at > started_at",
            name="ck_recording_segments_recording_segment_positive_window",
        ),
        sa.CheckConstraint(
            "duration_ms > 0",
            name="ck_recording_segments_recording_segment_positive_duration",
        ),
        sa.CheckConstraint(
            "timing_status IN ('PROVISIONAL','FINAL')",
            name="ck_recording_segments_recording_segment_timing_status",
        ),
        sa.CheckConstraint(
            "timing_source IN ('HOOK_RAW','NEXT_SEGMENT_BOUNDARY','RECORDER_STOP','SOURCE_UNREGISTER','RECOVERY')",
            name="ck_recording_segments_recording_segment_timing_source",
        ),
        sa.CheckConstraint(
            "integrity_status IN ('UNKNOWN','OK','DEGRADED','CORRUPT')",
            name="ck_recording_segments_recording_segment_integrity_status",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_recording_segments_camera_id_cameras",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stream_profile_id"],
            ["camera_stream_profiles.id"],
            name="fk_recording_segments_stream_profile_id_camera_stream_profiles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_segments"),
    )
    op.create_index(
        "ix_recording_segments_camera_started_at",
        "recording_segments",
        ["camera_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_recording_segments_camera_end_start_id",
        "recording_segments",
        ["camera_id", "ended_at", "started_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_recording_segments_continuity_created",
        "recording_segments",
        ["continuity_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "recording_locations",
        sa.Column("recording_segment_id", sa.Uuid(), nullable=False),
        sa.Column("storage_target_id", sa.Uuid(), nullable=False),
        sa.Column("object_path", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=256), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "state IN ('AVAILABLE','ARCHIVING','FAILED','DELETING','DELETED','MISSING')",
            name="ck_recording_locations_recording_location_state",
        ),
        sa.ForeignKeyConstraint(
            ["recording_segment_id"],
            ["recording_segments.id"],
            name="fk_recording_locations_recording_segment_id_recording_segments",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["storage_target_id"],
            ["storage_targets.id"],
            name="fk_recording_locations_storage_target_id_storage_targets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_locations"),
        sa.UniqueConstraint(
            "storage_target_id",
            "object_path",
            name="uq_recording_locations_target_path",
        ),
    )
    op.create_index(
        "ix_recording_locations_segment_target_state",
        "recording_locations",
        ["recording_segment_id", "storage_target_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_recording_locations_target_state_segment",
        "recording_locations",
        ["storage_target_id", "state", "recording_segment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recording_locations_target_state_segment",
        table_name="recording_locations",
    )
    op.drop_index(
        "ix_recording_locations_segment_target_state",
        table_name="recording_locations",
    )
    op.drop_table("recording_locations")

    op.drop_index(
        "ix_recording_segments_continuity_created",
        table_name="recording_segments",
    )
    op.drop_index(
        "ix_recording_segments_camera_end_start_id",
        table_name="recording_segments",
    )
    op.drop_index(
        "ix_recording_segments_camera_started_at",
        table_name="recording_segments",
    )
    op.drop_table("recording_segments")

    op.drop_index(
        "ix_recording_triggers_camera_state_end",
        table_name="recording_triggers",
    )
    op.drop_index(
        "uq_recording_triggers_source_event",
        table_name="recording_triggers",
    )
    op.drop_table("recording_triggers")
    op.drop_table("recording_policies")
    op.drop_table("storage_targets")
