"""alerts and notification delivery history

Revision ID: 0006_alerts_notifications
Revises: 0005_events
Create Date: 2026-09-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_alerts_notifications"
down_revision: str | Sequence[str] | None = "0005_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_policies",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("match_json", sa.JSON(), nullable=False),
        sa.Column("action_json", sa.JSON(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "cooldown_seconds >= 0",
            name="ck_alert_policies_alert_policy_cooldown_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_alert_policies"),
        sa.UniqueConstraint("name", name="uq_alert_policies_name"),
    )

    op.create_table(
        "notification_targets",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("secret_ref", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('apprise')",
            name="ck_notification_targets_notification_target_kind",
        ),
        sa.ForeignKeyConstraint(
            ["secret_ref"],
            ["secret_records.id"],
            name="fk_notification_targets_secret_ref_secret_records",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_targets"),
        sa.UniqueConstraint("name", name="uq_notification_targets_name"),
    )

    op.create_table(
        "alerts",
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('OPEN','ACKNOWLEDGED','RESOLVED')",
            name="ck_alerts_alert_state",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["alert_policies.id"],
            name="fk_alerts_policy_id_alert_policies",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_alerts_event_id_events",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name="fk_alerts_camera_id_cameras",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by"],
            ["users.id"],
            name="fk_alerts_acknowledged_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
        sa.UniqueConstraint(
            "policy_id",
            "event_id",
            name="uq_alerts_policy_event",
        ),
    )
    op.create_index(
        "ix_alerts_camera_created",
        "alerts",
        ["camera_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_alerts_state_created",
        "alerts",
        ["state", "created_at"],
        unique=False,
    )

    op.create_table(
        "notification_deliveries",
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
        sa.UniqueConstraint(
            "alert_id",
            "notification_target_id",
            name="uq_notification_deliveries_alert_target",
        ),
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


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_target_created",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_alert_created",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")

    op.drop_index(
        "ix_alerts_state_created",
        table_name="alerts",
    )
    op.drop_index(
        "ix_alerts_camera_created",
        table_name="alerts",
    )
    op.drop_table("alerts")

    op.drop_table("notification_targets")
    op.drop_table("alert_policies")
