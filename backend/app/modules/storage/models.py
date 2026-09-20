from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import UTCDateTime


class StorageTarget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "storage_targets"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('LOCAL_RECORDING','RCLONE_ARCHIVE','PLAYBACK_CACHE','BACKUP')",
            name="storage_target_kind",
        ),
        CheckConstraint(
            "health_state IN ('UNKNOWN','OK','PRESSURE','CRITICAL','OFFLINE','READ_ONLY')",
            name="storage_target_health_state",
        ),
    )

    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(
        "config",
        JSON,
        nullable=False,
        default=dict,
    )
    health_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="UNKNOWN",
    )
    last_health_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
