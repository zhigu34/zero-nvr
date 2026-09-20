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
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import UTCDateTime, UUIDType, utc_now


class RetentionPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "retention_policies"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('GLOBAL','CAMERA','CAMERA_GROUP')",
            name="retention_policy_scope_type",
        ),
        CheckConstraint(
            "mode IN ('BEST_EFFORT','HARD')",
            name="retention_policy_mode",
        ),
        CheckConstraint(
            "ordinary_keep_days >= 0",
            name="retention_policy_ordinary_days_nonnegative",
        ),
        CheckConstraint(
            "event_keep_days >= 0",
            name="retention_policy_event_days_nonnegative",
        ),
        CheckConstraint(
            "manual_keep_days >= 0",
            name="retention_policy_manual_days_nonnegative",
        ),
    )

    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    ordinary_keep_days: Mapped[int] = mapped_column(Integer, nullable=False)
    event_keep_days: Mapped[int] = mapped_column(Integer, nullable=False)
    manual_keep_days: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    require_archive_before_delete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )


class RecordingPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recording_policies"
    __table_args__ = (
        UniqueConstraint(
            "camera_id",
            name="uq_recording_policies_camera_id",
        ),
        CheckConstraint(
            "baseline_mode IN ('continuous','schedule','disabled')",
            name="recording_policy_baseline_mode",
        ),
        CheckConstraint(
            "segment_target_seconds > 0",
            name="recording_policy_segment_target_positive",
        ),
        CheckConstraint(
            "pre_roll_seconds >= 0",
            name="recording_policy_pre_roll_nonnegative",
        ),
        CheckConstraint(
            "post_roll_seconds >= 0",
            name="recording_policy_post_roll_nonnegative",
        ),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
    )
    baseline_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="continuous",
    )
    schedule_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    schedule_timezone: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    event_recording_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    event_filter_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    segment_target_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=300,
    )
    pre_roll_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
    )
    post_roll_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
    )
    storage_target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("storage_targets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    retention_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("retention_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )


class RecordingProtection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recording_protections"
    __table_args__ = (
        Index(
            "ix_recording_protections_camera_range",
            "camera_id",
            "started_at",
            "ended_at",
        ),
        CheckConstraint(
            "ended_at > started_at",
            name="recording_protection_positive_range",
        ),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )


class RecordingTrigger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recording_triggers"
    __table_args__ = (
        Index(
            "uq_recording_triggers_source_event",
            "source",
            "source_event_id",
            unique=True,
            sqlite_where=text("source_event_id IS NOT NULL"),
            postgresql_where=text("source_event_id IS NOT NULL"),
        ),
        Index(
            "ix_recording_triggers_camera_planned_start",
            "camera_id",
            "planned_start_at",
        ),
        CheckConstraint(
            "pre_roll_seconds >= 0",
            name="recording_trigger_pre_roll_nonnegative",
        ),
        CheckConstraint(
            "post_roll_seconds >= 0",
            name="recording_trigger_post_roll_nonnegative",
        ),
        CheckConstraint(
            "planned_end_at IS NULL OR planned_end_at >= planned_start_at",
            name="recording_trigger_window",
        ),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    pre_roll_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    post_roll_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_start_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    planned_end_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )


class RecordingSegment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "recording_segments"
    __table_args__ = (
        Index(
            "ix_recording_segments_camera_started",
            "camera_id",
            "started_at",
        ),
        Index(
            "ix_recording_segments_camera_ended_started_id",
            "camera_id",
            "ended_at",
            "started_at",
            "id",
        ),
        Index(
            "ix_recording_segments_source_identity",
            "source_media_server_id",
            "source_app",
            "source_stream",
            "started_at",
        ),
        CheckConstraint(
            "ended_at > started_at",
            name="recording_segment_positive_range",
        ),
        CheckConstraint(
            "duration_ms >= 0",
            name="recording_segment_duration_nonnegative",
        ),
        CheckConstraint(
            "timing_status IN ('PROVISIONAL','FINAL')",
            name="recording_segment_timing_status",
        ),
        CheckConstraint(
            "timing_source IN ('HOOK_RAW','NEXT_SEGMENT_BOUNDARY','EXPLICIT_STOP','RECOVERY')",
            name="recording_segment_timing_source",
        ),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stream_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("camera_stream_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    timing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    timing_source: Mapped[str] = mapped_column(String(64), nullable=False)
    recording_reasons_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    container: Mapped[str] = mapped_column(String(32), nullable=False)
    source_media_server_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    source_app: Mapped[str] = mapped_column(String(128), nullable=False)
    source_stream: Mapped[str] = mapped_column(String(256), nullable=False)
    integrity_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="UNKNOWN",
    )
    completion_reason: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )

    locations: Mapped[list["RecordingLocation"]] = relationship(
        back_populates="recording_segment",
        lazy="selectin",
    )


from app.modules.storage.models import RecordingLocation  # noqa: E402
