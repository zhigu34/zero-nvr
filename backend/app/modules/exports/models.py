from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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
from app.core.db.mixins import UUIDPrimaryKeyMixin
from app.core.db.types import UTCDateTime, UUIDType, utc_now


class ExportJob(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "exports"
    __table_args__ = (
        Index(
            "ix_exports_camera_created",
            "camera_id",
            "created_at",
        ),
        Index(
            "ix_exports_state_created",
            "state",
            "created_at",
        ),
        CheckConstraint(
            "requested_end_at > requested_start_at",
            name="export_positive_range",
        ),
        CheckConstraint(
            "format IN ('mp4')",
            name="export_format",
        ),
        CheckConstraint(
            "codec_mode IN ('auto','copy','h264')",
            name="export_codec_mode",
        ),
        CheckConstraint(
            "gap_policy IN ('skip','fail')",
            name="export_gap_policy",
        ),
        CheckConstraint(
            "state IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED','EXPIRED')",
            name="export_state",
        ),
        CheckConstraint(
            "requested_duration_ms > 0",
            name="export_requested_duration_positive",
        ),
        CheckConstraint(
            "actual_duration_ms IS NULL OR actual_duration_ms >= 0",
            name="export_actual_duration_nonnegative",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="export_size_nonnegative",
        ),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_start_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    requested_end_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    requested_duration_ms: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    format: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="mp4",
    )
    codec_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="auto",
    )
    gap_policy: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="skip",
    )
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PENDING",
    )
    output_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    actual_duration_ms: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    selected_segment_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )


class ExportShareToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "export_share_tokens"
    __table_args__ = (
        Index(
            "ix_export_share_tokens_export_created",
            "export_id",
            "created_at",
        ),
        CheckConstraint(
            "max_downloads IS NULL OR max_downloads > 0",
            name="export_share_max_downloads_positive",
        ),
        CheckConstraint(
            "download_count >= 0",
            name="export_share_download_count_nonnegative",
        ),
    )

    export_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("exports.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    max_downloads: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    download_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_download_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
