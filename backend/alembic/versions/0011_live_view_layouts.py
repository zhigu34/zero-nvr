"""add per-user live view layouts

Revision ID: 0011_live_view_layouts
Revises: 0010_notification_delivery
Create Date: 2026-09-21
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_live_view_layouts"
down_revision: str | Sequence[str] | None = (
    "0010_notification_delivery"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_view_layouts",
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "layout_json",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=(
                "fk_live_view_layouts_"
                "owner_user_id_users"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_live_view_layouts",
        ),
        sa.UniqueConstraint(
            "owner_user_id",
            "name",
            name=(
                "uq_live_view_layouts_owner_name"
            ),
        ),
    )
    op.create_index(
        "ix_live_view_layouts_owner_user_id",
        "live_view_layouts",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        "uq_live_view_layouts_owner_default",
        "live_view_layouts",
        ["owner_user_id"],
        unique=True,
        sqlite_where=sa.text("is_default"),
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_live_view_layouts_owner_default",
        table_name="live_view_layouts",
    )
    op.drop_index(
        "ix_live_view_layouts_owner_user_id",
        table_name="live_view_layouts",
    )
    op.drop_table("live_view_layouts")
