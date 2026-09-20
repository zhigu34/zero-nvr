"""soft camera retirement

Revision ID: 0009_camera_retirement
Revises: 0008_backups
Create Date: 2026-09-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_camera_retirement"
down_revision: str | Sequence[str] | None = "0008_backups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "retired_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_cameras_retired_at",
        "cameras",
        ["retired_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cameras_retired_at",
        table_name="cameras",
    )
    op.drop_column("cameras", "retired_at")
