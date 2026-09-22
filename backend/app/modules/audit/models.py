from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, JSON, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import UUIDPrimaryKeyMixin
from app.core.db.types import UTCDateTime, UUIDType, utc_now
from app.core.security import redact_sensitive_value, redact_text


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Actor-driven sensitive product change."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_actor_time", "actor_id", "occurred_at"),
        Index("ix_audit_events_camera_time", "camera_id", "occurred_at"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_info: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )


@event.listens_for(AuditEvent, "before_insert")
@event.listens_for(AuditEvent, "before_update")
def _redact_audit_event(
    _mapper: Any,
    _connection: Any,
    target: AuditEvent,
) -> None:
    target.client_info = redact_sensitive_value(
        target.client_info
    )
    target.before_json = redact_sensitive_value(
        target.before_json
    )
    target.after_json = redact_sensitive_value(
        target.after_json
    )
    target.metadata_json = redact_sensitive_value(
        target.metadata_json
    )
    if target.reason is not None:
        target.reason = redact_text(target.reason)
