"""camera device-time synchronization mode

Revision ID: 0015_camera_time_sync_mode
Revises: 0014_notification_smtp
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0015_camera_time_sync_mode"
down_revision: str | Sequence[str] | None = (
    "0014_notification_smtp"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table(
        "cameras"
    ) as batch:
        batch.add_column(
            sa.Column(
                "time_sync_mode",
                sa.String(length=16),
                nullable=False,
                server_default="monitor",
            )
        )

    op.execute(
        sa.text(
            """
            UPDATE cameras
            SET time_sync_mode = 'ignore'
            WHERE device_id IS NULL
               OR device_id IN (
                    SELECT id
                    FROM devices
                    WHERE adapter_type <> 'onvif'
               )
            """
        )
    )

    with op.batch_alter_table(
        "cameras"
    ) as batch:
        batch.create_check_constraint(
            "ck_cameras_camera_time_sync_mode",
            (
                "time_sync_mode IN "
                "('monitor','manage_ntp','ignore')"
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "cameras"
    ) as batch:
        batch.drop_constraint(
            "ck_cameras_camera_time_sync_mode",
            type_="check",
        )
        batch.drop_column(
            "time_sync_mode"
        )
