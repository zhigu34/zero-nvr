from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import UTCDateTime, UUIDType, utc_now


class StorageTarget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "storage_targets"
    __table_args__ = (
        CheckConstraint(
            "type IN ('local','rclone')",
            name="storage_target_type",
        ),
        CheckConstraint(
            "role IN ('recording','archive')",
            name="storage_target_role",
        ),
        Index(
            "ix_storage_targets_role_enabled",
            "role",
            "enabled",
        ),
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
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
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    credential_secret_ref: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("secret_records.id", ondelete="RESTRICT"),
        nullable=True,
    )


class RecordingLocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "recording_locations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('AVAILABLE','ARCHIVING','FAILED','DELETING','DELETED','MISSING')",
            name="recording_location_state",
        ),
        UniqueConstraint(
            "storage_target_id",
            "object_path",
            name="uq_recording_locations_target_object",
        ),
        Index(
            "ix_recording_locations_segment_target_state",
            "recording_segment_id",
            "storage_target_id",
            "state",
        ),
        Index(
            "ix_recording_locations_target_state_segment",
            "storage_target_id",
            "state",
            "recording_segment_id",
        ),
    )

    recording_segment_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("recording_segments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    storage_target_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("storage_targets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    object_path: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="AVAILABLE",
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(256), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )

    recording_segment: Mapped["RecordingSegment"] = relationship(
        back_populates="locations",
    )
    storage_target: Mapped[StorageTarget] = relationship(lazy="joined")


from app.modules.recordings.models import RecordingSegment  # noqa: E402
