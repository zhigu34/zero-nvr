"""add user email verification state

Revision ID: 0013_user_email_verified
Revises: 0012_notification_secret
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013_user_email_verified"
down_revision: str | Sequence[str] | None = (
    "0012_notification_secret"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "email_verified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("email_verified_at")
