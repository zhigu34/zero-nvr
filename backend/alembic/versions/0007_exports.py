"""export jobs and share tokens

Revision ID: 0007_exports
Revises: 0006_alerts_notifications
Create Date: 2026-09-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_exports"
down_revision: str | Sequence[str] | None = "0006_alerts_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exports",
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("requested_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("codec_mode", sa.String(length=16), nullable=False),
        sa.Column("gap_policy", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("actual_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("selected_segment_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "requested_end_at > requested_start_at",
            name="ck_exports_export_positive_range",
        ),
        sa.CheckConstraint(
            "format IN ('mp4')",
            name="ck_exports_export_format",
        ),
        sa.CheckConstraint(
            "codec_mode IN ('auto','copy','h264')",
            name="ck_exports_export_codec_mode",
        ),
        sa.CheckConstraint(
            "gap_policy IN ('skip','fail')",
            name="ck_exports_export_gap_policy",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED','EXPIRED')",
            name="ck_exports_export_state",
        ),
        sa.CheckConstraint(
            "requested_duration_ms > 0",
            name="ck_exports_export_requested_duration_positive",
        ),
        sa.CheckConstraint(
            "actual_duration_ms IS NULL OR actual_duration_ms >= 0",
            name="ck_exports_export_actual_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_exports_export_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_exports_camera_id_cameras",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name="fk_exports_requested_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exports"),
    )
    op.create_index(
        "ix_exports_camera_created",
        "exports",
        ["camera_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_exports_state_created",
        "exports",
        ["state", "created_at"],
        unique=False,
    )

    op.create_table(
        "export_share_tokens",
        sa.Column("export_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_downloads", sa.Integer(), nullable=True),
        sa.Column("download_count", sa.Integer(), nullable=False),
        sa.Column("last_download_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "max_downloads IS NULL OR max_downloads > 0",
            name="ck_export_share_tokens_export_share_max_downloads_positive",
        ),
        sa.CheckConstraint(
            "download_count >= 0",
            name="ck_export_share_tokens_export_share_download_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["export_id"],
            ["exports.id"],
            name="fk_export_share_tokens_export_id_exports",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_export_share_tokens_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_export_share_tokens"),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_export_share_tokens_token_hash",
        ),
    )
    op.create_index(
        "ix_export_share_tokens_export_created",
        "export_share_tokens",
        ["export_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_export_share_tokens_export_created",
        table_name="export_share_tokens",
    )
    op.drop_table("export_share_tokens")

    op.drop_index(
        "ix_exports_state_created",
        table_name="exports",
    )
    op.drop_index(
        "ix_exports_camera_created",
        table_name="exports",
    )
    op.drop_table("exports")
