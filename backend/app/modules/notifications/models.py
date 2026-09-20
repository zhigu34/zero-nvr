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
    UniqueConstraint,
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
    secret_ref: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("secret_records.id", ondelete="RESTRICT"),
        nullable=False,
    )


class NotificationDelivery(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "alert_id",
            "notification_target_id",
            name="uq_notification_deliveries_alert_target",
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
        CheckConstraint(
            "state IN ('PENDING','SENDING','SENT','FAILED','SKIPPED')",
            name="notification_delivery_state",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="notification_delivery_attempts_nonnegative",
        ),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("alerts.id", ondelete="RESTRICT"),
        nullable=False,
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
    attempts: Mapped[int] = mapped_column(
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
    delivered_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
