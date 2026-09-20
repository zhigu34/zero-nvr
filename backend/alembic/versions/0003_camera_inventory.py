"""camera inventory, stream bindings, groups, and camera scopes

Revision ID: 0003_camera_inventory
Revises: 0002_system_audit
Create Date: 2026-09-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_camera_inventory"
down_revision: str | Sequence[str] | None = "0002_system_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("manufacturer", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("serial_number", sa.String(length=256), nullable=True),
        sa.Column("hardware_id", sa.String(length=512), nullable=True),
        sa.Column("adapter_type", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("capabilities_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
    )
    op.create_index("ix_devices_hardware_id", "devices", ["hardware_id"], unique=False)
    op.create_index(
        "ix_devices_adapter_type_enabled",
        "devices",
        ["adapter_type", "enabled"],
        unique=False,
    )

    op.create_table(
        "discovery_sessions",
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_discovery_sessions_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_discovery_sessions"),
    )
    op.create_index(
        "ix_discovery_sessions_started_at",
        "discovery_sessions",
        ["started_at"],
        unique=False,
    )

    op.create_table(
        "cameras",
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("channel_key", sa.String(length=256), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("location", sa.String(length=256), nullable=True),
        sa.Column("storage_label", sa.String(length=128), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_cameras_device_id_devices",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cameras"),
        sa.UniqueConstraint(
            "device_id",
            "channel_key",
            name="uq_cameras_device_channel",
        ),
    )
    op.create_index(
        "ix_cameras_enabled_name",
        "cameras",
        ["enabled", "name"],
        unique=False,
    )

    op.create_table(
        "device_endpoints",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("host", sa.String(length=512), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("scheme", sa.String(length=32), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_device_endpoints_device_id_devices",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_device_endpoints"),
    )
    op.create_index(
        "ix_device_endpoints_device_enabled",
        "device_endpoints",
        ["device_id", "enabled"],
        unique=False,
    )

    op.create_table(
        "device_credentials",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("secret_ref", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_device_credentials_device_id_devices",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["device_endpoints.id"],
            name="fk_device_credentials_endpoint_id_device_endpoints",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["secret_ref"],
            ["secret_records.id"],
            name="fk_device_credentials_secret_ref_secret_records",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_device_credentials"),
    )
    op.create_index(
        "ix_device_credentials_device_kind",
        "device_credentials",
        ["device_id", "kind"],
        unique=False,
    )

    op.create_table(
        "discovery_candidates",
        sa.Column("discovery_session_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_key", sa.String(length=512), nullable=False),
        sa.Column("host", sa.String(length=512), nullable=True),
        sa.Column("device_identity", sa.JSON(), nullable=False),
        sa.Column("display_info", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["discovery_session_id"],
            ["discovery_sessions.id"],
            name="fk_discovery_candidates_discovery_session_id_discovery_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_discovery_candidates"),
        sa.UniqueConstraint(
            "discovery_session_id",
            "candidate_key",
            name="uq_discovery_candidates_session_key",
        ),
    )

    op.create_table(
        "camera_stream_profiles",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("adapter_profile_key", sa.String(length=512), nullable=False),
        sa.Column("video_source_key", sa.String(length=512), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("codec", sa.String(length=32), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("bitrate_kbps", sa.Integer(), nullable=True),
        sa.Column("bitrate_mode", sa.String(length=32), nullable=True),
        sa.Column("gop_seconds", sa.Float(), nullable=True),
        sa.Column("audio_codec", sa.String(length=32), nullable=True),
        sa.Column("has_audio", sa.Boolean(), nullable=False),
        sa.Column("stream_uri_ref", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_camera_stream_profiles_camera_id_cameras",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stream_uri_ref"],
            ["secret_records.id"],
            name="fk_camera_stream_profiles_stream_uri_ref_secret_records",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_camera_stream_profiles"),
        sa.UniqueConstraint(
            "camera_id",
            "adapter_profile_key",
            name="uq_camera_stream_profiles_camera_adapter_key",
        ),
    )
    op.create_index(
        "ix_camera_stream_profiles_camera_status",
        "camera_stream_profiles",
        ["camera_id", "status"],
        unique=False,
    )

    op.create_table(
        "camera_stream_bindings",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("stream_profile_id", sa.Uuid(), nullable=False),
        sa.Column("selection_mode", sa.String(length=16), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('RECORD','LIVE_HIGH','LIVE_LOW','AI_DETECT','SNAPSHOT','AUDIO')",
            name="ck_camera_stream_bindings_camera_stream_binding_purpose",
        ),
        sa.CheckConstraint(
            "selection_mode IN ('auto','manual')",
            name="ck_camera_stream_bindings_camera_stream_binding_selection_mode",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_camera_stream_bindings_camera_id_cameras",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stream_profile_id"],
            ["camera_stream_profiles.id"],
            name="fk_camera_stream_bindings_stream_profile_id_camera_stream_profiles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_camera_stream_bindings"),
        sa.UniqueConstraint(
            "camera_id",
            "purpose",
            name="uq_camera_stream_bindings_camera_purpose",
        ),
    )

    op.create_table(
        "camera_groups",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["camera_groups.id"],
            name="fk_camera_groups_parent_id_camera_groups",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_camera_groups"),
        sa.UniqueConstraint("name", name="uq_camera_groups_name"),
    )

    op.create_table(
        "camera_group_members",
        sa.Column("camera_group_id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["camera_group_id"],
            ["camera_groups.id"],
            name="fk_camera_group_members_camera_group_id_camera_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_camera_group_members_camera_id_cameras",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "camera_group_id",
            "camera_id",
            name="pk_camera_group_members",
        ),
    )

    op.create_table(
        "principal_camera_scopes",
        sa.Column("principal_type", sa.String(length=16), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("scope_mode", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "principal_type IN ('user','role')",
            name="ck_principal_camera_scopes_principal_camera_scope_type",
        ),
        sa.CheckConstraint(
            "scope_mode IN ('all','selected','none')",
            name="ck_principal_camera_scopes_principal_camera_scope_mode",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_principal_camera_scopes"),
        sa.UniqueConstraint(
            "principal_type",
            "principal_id",
            name="uq_principal_camera_scopes_principal",
        ),
    )

    op.create_table(
        "principal_camera_scope_entries",
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("camera_group_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(camera_id IS NOT NULL AND camera_group_id IS NULL) OR "
            "(camera_id IS NULL AND camera_group_id IS NOT NULL)",
            name="ck_principal_camera_scope_entries_principal_camera_scope_entry_one_target",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["principal_camera_scopes.id"],
            name="fk_principal_camera_scope_entries_scope_id_principal_camera_scopes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_principal_camera_scope_entries_camera_id_cameras",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["camera_group_id"],
            ["camera_groups.id"],
            name="fk_principal_camera_scope_entries_camera_group_id_camera_groups",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_principal_camera_scope_entries"),
    )
    op.create_index(
        "uq_principal_camera_scope_entries_camera",
        "principal_camera_scope_entries",
        ["scope_id", "camera_id"],
        unique=True,
        sqlite_where=sa.text("camera_id IS NOT NULL"),
        postgresql_where=sa.text("camera_id IS NOT NULL"),
    )
    op.create_index(
        "uq_principal_camera_scope_entries_group",
        "principal_camera_scope_entries",
        ["scope_id", "camera_group_id"],
        unique=True,
        sqlite_where=sa.text("camera_group_id IS NOT NULL"),
        postgresql_where=sa.text("camera_group_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_principal_camera_scope_entries_group",
        table_name="principal_camera_scope_entries",
    )
    op.drop_index(
        "uq_principal_camera_scope_entries_camera",
        table_name="principal_camera_scope_entries",
    )
    op.drop_table("principal_camera_scope_entries")
    op.drop_table("principal_camera_scopes")
    op.drop_table("camera_group_members")
    op.drop_table("camera_groups")
    op.drop_table("camera_stream_bindings")
    op.drop_index(
        "ix_camera_stream_profiles_camera_status",
        table_name="camera_stream_profiles",
    )
    op.drop_table("camera_stream_profiles")
    op.drop_table("discovery_candidates")
    op.drop_index(
        "ix_device_credentials_device_kind",
        table_name="device_credentials",
    )
    op.drop_table("device_credentials")
    op.drop_index(
        "ix_device_endpoints_device_enabled",
        table_name="device_endpoints",
    )
    op.drop_table("device_endpoints")
    op.drop_index("ix_cameras_enabled_name", table_name="cameras")
    op.drop_table("cameras")
    op.drop_index(
        "ix_discovery_sessions_started_at",
        table_name="discovery_sessions",
    )
    op.drop_table("discovery_sessions")
    op.drop_index(
        "ix_devices_adapter_type_enabled",
        table_name="devices",
    )
    op.drop_index("ix_devices_hardware_id", table_name="devices")
    op.drop_table("devices")
