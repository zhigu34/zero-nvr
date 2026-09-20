"""align notification delivery with frozen V1 schema

Revision ID: 0010_notification_delivery
Revises: 0009_camera_retirement
Create Date: 2026-09-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_notification_delivery"
down_revision: str | Sequence[str] | None = "0009_camera_retirement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_v2(name: str) -> None:
    op.create_table(
        name,
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("notification_target_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("provider_message_id", sa.String(length=512), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('alert','password_reset','security','system_test')",
            name="ck_notification_deliveries_notification_delivery_purpose",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING','SENDING','SENT','FAILED','SKIPPED')",
            name="ck_notification_deliveries_notification_delivery_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_notification_deliveries_notification_delivery_attempt_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            name="fk_notification_deliveries_alert_id_alerts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notification_target_id"],
            ["notification_targets.id"],
            name="fk_notification_deliveries_notification_target_id_notification_targets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_notification_deliveries",
        ),
    )


def upgrade() -> None:
    temporary = "notification_deliveries_v2"
    _create_v2(temporary)

    op.execute(
        sa.text(
            f"""
            INSERT INTO {temporary} (
                alert_id,
                purpose,
                notification_target_id,
                state,
                attempt_count,
                title,
                body,
                last_attempt_at,
                sent_at,
                last_error_code,
                provider_message_id,
                correlation_id,
                id,
                created_at,
                updated_at
            )
            SELECT
                alert_id,
                'alert',
                notification_target_id,
                state,
                attempts,
                title,
                body,
                last_attempt_at,
                delivered_at,
                last_error_code,
                NULL,
                CAST(alert_id AS TEXT),
                id,
                created_at,
                created_at
            FROM notification_deliveries
            """
        )
    )

    op.drop_table("notification_deliveries")
    op.rename_table(temporary, "notification_deliveries")

    op.create_index(
        "uq_notification_deliveries_alert_target",
        "notification_deliveries",
        ["alert_id", "notification_target_id"],
        unique=True,
    )
    op.create_index(
        "ix_notification_deliveries_alert_created",
        "notification_deliveries",
        ["alert_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_target_created",
        "notification_deliveries",
        ["notification_target_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_purpose_created",
        "notification_deliveries",
        ["purpose", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_correlation",
        "notification_deliveries",
        ["correlation_id"],
        unique=False,
    )


def downgrade() -> None:
    temporary = "notification_deliveries_v1"
    op.create_table(
        temporary,
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("notification_target_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('PENDING','SENDING','SENT','FAILED','SKIPPED')",
            name="ck_notification_deliveries_notification_delivery_state",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_notification_deliveries_notification_delivery_attempts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            name="fk_notification_deliveries_alert_id_alerts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notification_target_id"],
            ["notification_targets.id"],
            name="fk_notification_deliveries_notification_target_id_notification_targets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_notification_deliveries",
        ),
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO {temporary} (
                alert_id,
                notification_target_id,
                state,
                attempts,
                title,
                body,
                last_attempt_at,
                delivered_at,
                last_error_code,
                id,
                created_at
            )
            SELECT
                alert_id,
                notification_target_id,
                state,
                attempt_count,
                title,
                body,
                last_attempt_at,
                sent_at,
                last_error_code,
                id,
                created_at
            FROM notification_deliveries
            WHERE purpose = 'alert'
              AND alert_id IS NOT NULL
            """
        )
    )

    op.drop_table("notification_deliveries")
    op.rename_table(temporary, "notification_deliveries")

    op.create_index(
        "uq_notification_deliveries_alert_target",
        "notification_deliveries",
        ["alert_id", "notification_target_id"],
        unique=True,
    )
    op.create_index(
        "ix_notification_deliveries_alert_created",
        "notification_deliveries",
        ["alert_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_target_created",
        "notification_deliveries",
        ["notification_target_id", "created_at"],
        unique=False,
    )
