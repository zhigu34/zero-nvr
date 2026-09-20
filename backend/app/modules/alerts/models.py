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
from app.core.db.types import UTCDateTime, UUIDType


class AlertPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_policies"
    __table_args__ = (
        CheckConstraint(
            "cooldown_seconds >= 0",
            name="alert_policy_cooldown_nonnegative",
        ),
    )

    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    severity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="info",
    )
    match_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    action_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    cooldown_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )


class Alert(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint(
            "policy_id",
            "event_id",
            name="uq_alerts_policy_event",
        ),
        Index(
            "ix_alerts_camera_created",
            "camera_id",
            "created_at",
        ),
        Index(
            "ix_alerts_state_created",
            "state",
            "created_at",
        ),
        CheckConstraint(
            "state IN ('OPEN','ACKNOWLEDGED','RESOLVED')",
            name="alert_state",
        ),
    )

    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("alert_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=True,
    )
    severity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="OPEN",
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
