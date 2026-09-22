"""allow SMTP notification targets

Revision ID: 0014_notification_smtp
Revises: 0013_user_email_verified
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op


revision: str = "0014_notification_smtp"
down_revision: str | Sequence[str] | None = (
    "0013_user_email_verified"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table(
        "notification_targets"
    ) as batch:
        batch.drop_constraint(
            "notification_target_kind",
            type_="check",
        )
        batch.create_check_constraint(
            "notification_target_kind",
            "kind IN ('apprise','smtp')",
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "notification_targets"
    ) as batch:
        batch.drop_constraint(
            "notification_target_kind",
            type_="check",
        )
        batch.create_check_constraint(
            "notification_target_kind",
            "kind IN ('apprise')",
        )
