"""recording policy, retention, catalog, and storage targets

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
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("credential_secret_ref", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('local','rclone')",
            name="ck_storage_targets_storage_target_type",
        ),
        sa.CheckConstraint(
            "role IN ('recording','archive')",
            name="ck_storage_targets_storage_target_role",
        ),
        sa.ForeignKeyConstraint(
            ["credential_secret_ref"],
            ["secret_records.id"],
            name="fk_storage_targets_credential_secret_ref_secret_records",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storage_targets"),
        sa.UniqueConstraint("name", name="uq_storage_targets_name"),
    )
    op.create_index(
        "ix_storage_targets_role_enabled",
        "storage_targets",
        ["role", "enabled"],
        unique=False,
    )

    op.create_table(
        "retention_policies",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("ordinary_keep_days", sa.Integer(), nullable=False),
        sa.Column("event_keep_days", sa.Integer(), nullable=False),
        sa.Column("manual_keep_days", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("require_archive_before_delete", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('GLOBAL','CAMERA','CAMERA_GROUP')",
            name="ck_retention_policies_retention_policy_scope_type",
        ),
        sa.CheckConstraint(
            "mode IN ('BEST_EFFORT','HARD')",
            name="ck_retention_policies_retention_policy_mode",
        ),
        sa.CheckConstraint(
            "ordinary_keep_days >= 0",
            name="ck_retention_policies_retention_policy_ordinary_days_nonnegative",
        ),
        sa.CheckConstraint(
            "event_keep_days >= 0",
            name="ck_retention_policies_retention_policy_event_days_nonnegative",
        ),
        sa.CheckConstraint(
            "manual_keep_days >= 0",
            name="ck_retention_policies_retention_policy_manual_days_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retention_policies"),
        sa.UniqueConstraint("name", name="uq_retention_policies_name"),
    )

    op.create_table(
        "recording_policies",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_mode", sa.String(length=32), nullable=False),
        sa.Column("schedule_json", sa.JSON(), nullable=False),
        sa.Column("schedule_timezone", sa.String(length=128), nullable=True),
        sa.Column("event_recording_enabled", sa.Boolean(), nullable=False),
        sa.Column("event_filter_json", sa.JSON(), nullable=False),
        sa.Column("segment_target_seconds", sa.Integer(), nullable=False),
        sa.Column("pre_roll_seconds", sa.Integer(), nullable=False),
        sa.Column("post_roll_seconds", sa.Integer(), nullable=False),
        sa.Column("storage_target_id", sa.Uuid(), nullable=True),
        sa.Column("retention_policy_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "baseline_mode IN ('continuous','schedule','disabled')",
            name="ck_recording_policies_recording_policy_baseline_mode",
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
        sa.ForeignKeyConstraint(
            ["retention_policy_id"],
            ["retention_policies.id"],
            name="fk_recording_policies_retention_policy_id_retention_policies",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_policies"),
        sa.UniqueConstraint(
            "camera_id",
            name="uq_recording_policies_camera_id",
        ),
    )

    op.create_table(
        "recording_protections",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ended_at > started_at",
            name="ck_recording_protections_recording_protection_positive_range",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_recording_protections_camera_id_cameras",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_recording_protections_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_protections"),
    )
    op.create_index(
        "ix_recording_protections_camera_range",
        "recording_protections",
        ["camera_id", "started_at", "ended_at"],
        unique=False,
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
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "pre_roll_seconds >= 0",
            name="ck_recording_triggers_recording_trigger_pre_roll_nonnegative",
        ),
        sa.CheckConstraint(
            "post_roll_seconds >= 0",
            name="ck_recording_triggers_recording_trigger_post_roll_nonnegative",
        ),
        sa.CheckConstraint(
            "planned_end_at IS NULL OR planned_end_at >= planned_start_at",
            name="ck_recording_triggers_recording_trigger_window",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_recording_triggers_camera_id_cameras",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_triggers"),
    )
    op.create_index(
        "uq_recording_triggers_source_event",
        "recording_triggers",
        ["source", "source_event_id"],
        unique=True,
        sqlite_where=sa.text("source_event_id IS NOT NULL"),
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )
    op.create_index(
        "ix_recording_triggers_camera_planned_start",
        "recording_triggers",
        ["camera_id", "planned_start_at"],
        unique=False,
    )

    op.create_table(
        "recording_segments",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("stream_profile_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("timing_status", sa.String(length=32), nullable=False),
        sa.Column("timing_source", sa.String(length=64), nullable=False),
        sa.Column("recording_reasons_json", sa.JSON(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("codec", sa.String(length=32), nullable=True),
        sa.Column("container", sa.String(length=32), nullable=False),
        sa.Column("source_media_server_id", sa.String(length=128), nullable=False),
        sa.Column("source_app", sa.String(length=128), nullable=False),
        sa.Column("source_stream", sa.String(length=256), nullable=False),
        sa.Column("integrity_status", sa.String(length=32), nullable=False),
        sa.Column("completion_reason", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ended_at > started_at",
            name="ck_recording_segments_recording_segment_positive_range",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="ck_recording_segments_recording_segment_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "timing_status IN ('PROVISIONAL','FINAL')",
            name="ck_recording_segments_recording_segment_timing_status",
        ),
        sa.CheckConstraint(
            "timing_source IN ('HOOK_RAW','NEXT_SEGMENT_BOUNDARY','EXPLICIT_STOP','RECOVERY')",
            name="ck_recording_segments_recording_segment_timing_source",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_recording_segments_camera_id_cameras",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stream_profile_id"],
            ["camera_stream_profiles.id"],
            name="fk_recording_segments_stream_profile_id_camera_stream_profiles",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_segments"),
    )
    op.create_index(
        "ix_recording_segments_camera_started",
        "recording_segments",
        ["camera_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_recording_segments_camera_ended_started_id",
        "recording_segments",
        ["camera_id", "ended_at", "started_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_recording_segments_source_identity",
        "recording_segments",
        [
            "source_media_server_id",
            "source_app",
            "source_stream",
            "started_at",
        ],
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
            ondelete="RESTRICT",
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
            name="uq_recording_locations_target_object",
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
        "ix_recording_segments_source_identity",
        table_name="recording_segments",
    )
    op.drop_index(
        "ix_recording_segments_camera_ended_started_id",
        table_name="recording_segments",
    )
    op.drop_index(
        "ix_recording_segments_camera_started",
        table_name="recording_segments",
    )
    op.drop_table("recording_segments")

    op.drop_index(
        "ix_recording_triggers_camera_planned_start",
        table_name="recording_triggers",
    )
    op.drop_index(
        "uq_recording_triggers_source_event",
        table_name="recording_triggers",
    )
    op.drop_table("recording_triggers")

    op.drop_index(
        "ix_recording_protections_camera_range",
        table_name="recording_protections",
    )
    op.drop_table("recording_protections")

    op.drop_table("recording_policies")
    op.drop_table("retention_policies")

    op.drop_index(
        "ix_storage_targets_role_enabled",
        table_name="storage_targets",
    )
    op.drop_table("storage_targets")
