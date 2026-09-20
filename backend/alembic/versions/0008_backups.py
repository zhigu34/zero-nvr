"""backup policies and recovery-point history

Revision ID: 0008_backups
Revises: 0007_exports
Create Date: 2026-09-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_backups"
down_revision: str | Sequence[str] | None = "0007_exports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_policies",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("repository_config_ref", sa.Uuid(), nullable=False),
        sa.Column("credential_secret_ref", sa.Uuid(), nullable=True),
        sa.Column("database_backend", sa.String(length=32), nullable=False),
        sa.Column("schedule", sa.JSON(), nullable=False),
        sa.Column("retention_policy_json", sa.JSON(), nullable=False),
        sa.Column("verify_after_backup", sa.Boolean(), nullable=False),
        sa.Column("repository_check_schedule", sa.JSON(), nullable=False),
        sa.Column("include_deployment_config", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "database_backend IN ('sqlite','postgresql')",
            name="ck_backup_policies_backup_policy_database_backend",
        ),
        sa.ForeignKeyConstraint(
            ["repository_config_ref"],
            ["secret_records.id"],
            name="fk_backup_policies_repository_config_ref_secret_records",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credential_secret_ref"],
            ["secret_records.id"],
            name="fk_backup_policies_credential_secret_ref_secret_records",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_backup_policies"),
        sa.UniqueConstraint("name", name="uq_backup_policies_name"),
    )

    op.create_table(
        "backup_sets",
        sa.Column("backup_policy_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("schedule_slot", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("app_version", sa.String(length=64), nullable=False),
        sa.Column("schema_revision", sa.String(length=128), nullable=False),
        sa.Column("database_engine", sa.String(length=32), nullable=False),
        sa.Column("restic_snapshot_id", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("verification_state", sa.String(length=32), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("sanitized_error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('PENDING','RUNNING','COMPLETED','FAILED')",
            name="ck_backup_sets_backup_set_state",
        ),
        sa.CheckConstraint(
            "verification_state IN ('PENDING','PASSED','FAILED','SKIPPED')",
            name="ck_backup_sets_backup_set_verification_state",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_backup_sets_backup_set_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["backup_policy_id"],
            ["backup_policies.id"],
            name="fk_backup_sets_backup_policy_id_backup_policies",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_backup_sets"),
        sa.UniqueConstraint(
            "backup_policy_id",
            "schedule_slot",
            name="uq_backup_sets_policy_schedule_slot",
        ),
    )
    op.create_index(
        "ix_backup_sets_policy_started",
        "backup_sets",
        ["backup_policy_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_backup_sets_state_started",
        "backup_sets",
        ["state", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_backup_sets_state_started",
        table_name="backup_sets",
    )
    op.drop_index(
        "ix_backup_sets_policy_started",
        table_name="backup_sets",
    )
    op.drop_table("backup_sets")
    op.drop_table("backup_policies")
