from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import UTCDateTime, UUIDType


class Event(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        Index(
            "uq_events_provider_identity",
            "source",
            "source_instance_id",
            "source_event_id",
            unique=True,
            sqlite_where=text("source_event_id IS NOT NULL"),
            postgresql_where=text("source_event_id IS NOT NULL"),
        ),
        Index(
            "ix_events_camera_started",
            "camera_id",
            "started_at",
        ),
        Index(
            "ix_events_source_started",
            "source",
            "started_at",
        ),
        Index(
            "ix_events_category_started",
            "category",
            "started_at",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="event_time_range",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="event_confidence_range",
        ),
        CheckConstraint(
            "source_event_id IS NULL OR source_instance_id IS NOT NULL",
            name="event_provider_identity_complete",
        ),
    )

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_instance_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )
    source_event_id: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=True,
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    zone: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
