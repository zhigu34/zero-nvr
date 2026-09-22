"""camera maintenance state

Revision ID: 0017_camera_maintenance
Revises: 0016_camera_config_revision
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0017_camera_maintenance"
down_revision: str | Sequence[str] | None = (
    "0016_camera_config_revision"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.add_column(
            sa.Column(
                "maintenance",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.drop_column("maintenance")
