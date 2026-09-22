from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import UTCDateTime, UUIDType, utc_now


class NotificationTarget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_targets"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('apprise')",
            name="notification_target_kind",
        ),
    )

    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="apprise",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    secret_ref: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("secret_records.id", ondelete="RESTRICT"),
        nullable=True,
    )


class NotificationDelivery(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index(
            "uq_notification_deliveries_alert_target",
            "alert_id",
            "notification_target_id",
            unique=True,
        ),
        Index(
            "ix_notification_deliveries_alert_created",
            "alert_id",
            "created_at",
        ),
        Index(
            "ix_notification_deliveries_target_created",
            "notification_target_id",
            "created_at",
        ),
        Index(
            "ix_notification_deliveries_purpose_created",
            "purpose",
            "created_at",
        ),
        Index(
            "ix_notification_deliveries_correlation",
            "correlation_id",
        ),
        CheckConstraint(
            "purpose IN ('alert','password_reset','security','system_test')",
            name="notification_delivery_purpose",
        ),
        CheckConstraint(
            "state IN ('PENDING','SENDING','SENT','FAILED','SKIPPED')",
            name="notification_delivery_state",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="notification_delivery_attempt_count_nonnegative",
        ),
    )

    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("alerts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    purpose: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="alert",
    )
    notification_target_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("notification_targets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PENDING",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    provider_message_id: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
