"""canonical provider-neutral events

Revision ID: 0005_events
Revises: 0004_recording_catalog
Create Date: 2026-09-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_events"
down_revision: str | Sequence[str] | None = "0004_recording_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "source_instance_id",
            sa.String(length=256),
            nullable=True,
        ),
        sa.Column(
            "source_event_id",
            sa.String(length=512),
            nullable=True,
        ),
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "ended_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=True),
        sa.Column("zone", sa.String(length=128), nullable=True),
        sa.Column("snapshot_ref", sa.Text(), nullable=True),
        sa.Column(
            "correlation_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_events_event_time_range",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_events_event_confidence_range",
        ),
        sa.CheckConstraint(
            "source_event_id IS NULL OR source_instance_id IS NOT NULL",
            name="ck_events_event_provider_identity_complete",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_events_camera_id_cameras",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
    )
    op.create_index(
        "uq_events_provider_identity",
        "events",
        ["source", "source_instance_id", "source_event_id"],
        unique=True,
        sqlite_where=sa.text("source_event_id IS NOT NULL"),
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )
    op.create_index(
        "ix_events_camera_started",
        "events",
        ["camera_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_events_source_started",
        "events",
        ["source", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_events_category_started",
        "events",
        ["category", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_events_category_started",
        table_name="events",
    )
    op.drop_index(
        "ix_events_source_started",
        table_name="events",
    )
    op.drop_index(
        "ix_events_camera_started",
        table_name="events",
    )
    op.drop_index(
        "uq_events_provider_identity",
        table_name="events",
    )
    op.drop_table("events")
