"""camera config revision fencing

Revision ID: 0016_camera_config_revision
Revises: 0015_camera_time_sync_mode
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0016_camera_config_revision"
down_revision: str | Sequence[str] | None = (
    "0015_camera_time_sync_mode"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.add_column(
            sa.Column(
                "config_revision",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.create_check_constraint(
            "ck_cameras_camera_config_revision_positive",
            "config_revision >= 1",
        )


def downgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.drop_constraint(
            "ck_cameras_camera_config_revision_positive",
            type_="check",
        )
        batch.drop_column("config_revision")
