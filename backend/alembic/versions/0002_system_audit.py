"""system settings and audit events

Revision ID: 0002_system_audit
Revises: 0001_auth_rbac
Create Date: 2026-09-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_system_audit"
down_revision: str | Sequence[str] | None = "0001_auth_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("namespace", sa.String(length=128), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("namespace", name="pk_system_settings"),
    )

    op.create_table(
        "audit_events",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("client_info", sa.JSON(), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_occurred_at",
        "audit_events",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_actor_time",
        "audit_events",
        ["actor_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_camera_time",
        "audit_events",
        ["camera_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_resource",
        "audit_events",
        ["resource_type", "resource_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_resource", table_name="audit_events")
    op.drop_index("ix_audit_events_camera_time", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_time", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("system_settings")
