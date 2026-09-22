"""allow clearing notification target credential

Revision ID: 0012_notification_secret_optional
Revises: 0011_live_view_layouts
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0012_notification_secret_optional"
down_revision: str | Sequence[str] | None = (
    "0011_live_view_layouts"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table(
        "notification_targets"
    ) as batch:
        batch.alter_column(
            "secret_ref",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "notification_targets"
    ) as batch:
        batch.alter_column(
            "secret_ref",
            existing_type=sa.Uuid(),
            nullable=False,
        )
