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


class RecordingPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recording_policies"
    __table_args__ = (
        UniqueConstraint(
            "camera_id",
            name="uq_recording_policies_camera_id",
        ),
        CheckConstraint(
            "mode IN ('CONTINUOUS','SCHEDULE','EVENT_ONLY','DISABLED')",
            name="recording_policy_mode",
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
    mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="CONTINUOUS",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    storage_target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("storage_targets.id", ondelete="RESTRICT"),
        nullable=True,
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
    schedule_timezone: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    schedule_json: Mapped[list[dict[str, Any]]] = mapped_column(
        "schedule",
        JSON,
        nullable=False,
        default=list,
    )


class RecordingTrigger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recording_triggers"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PENDING','ACTIVE','COMPLETED','CANCELLED','FAILED')",
            name="recording_trigger_state",
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
            "planned_end_at >= planned_start_at",
            name="recording_trigger_window",
        ),
        Index(
            "uq_recording_triggers_source_event",
            "camera_id",
            "source",
            "source_event_id",
            unique=True,
            sqlite_where=text("source_event_id IS NOT NULL"),
            postgresql_where=text("source_event_id IS NOT NULL"),
        ),
        Index(
            "ix_recording_triggers_camera_state_end",
            "camera_id",
            "state",
            "planned_end_at",
        ),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="CASCADE"),
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
    planned_start_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    planned_end_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PENDING",
    )
    reason: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )


class RecordingSegment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recording_segments"
    __table_args__ = (
        CheckConstraint(
            "ended_at > started_at",
            name="recording_segment_positive_window",
        ),
        CheckConstraint(
            "duration_ms > 0",
            name="recording_segment_positive_duration",
        ),
        CheckConstraint(
            "timing_status IN ('PROVISIONAL','FINAL')",
            name="recording_segment_timing_status",
        ),
        CheckConstraint(
            "timing_source IN ('HOOK_RAW','NEXT_SEGMENT_BOUNDARY','RECORDER_STOP','SOURCE_UNREGISTER','RECOVERY')",
            name="recording_segment_timing_source",
        ),
        CheckConstraint(
            "integrity_status IN ('UNKNOWN','OK','DEGRADED','CORRUPT')",
            name="recording_segment_integrity_status",
        ),
        Index(
            "ix_recording_segments_camera_started_at",
            "camera_id",
            "started_at",
        ),
        Index(
            "ix_recording_segments_camera_end_start_id",
            "camera_id",
            "ended_at",
            "started_at",
            "id",
        ),
        Index(
            "ix_recording_segments_continuity_created",
            "continuity_id",
            "created_at",
        ),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
    )
    stream_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("camera_stream_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    ended_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    recording_reasons: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    container: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="fmp4",
    )
    source_media_server_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="default",
    )
    source_app: Mapped[str] = mapped_column(String(128), nullable=False)
    source_stream: Mapped[str] = mapped_column(String(256), nullable=False)
    integrity_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="UNKNOWN",
    )
    completion_reason: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="NORMAL",
    )
    timing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PROVISIONAL",
    )
    timing_source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="HOOK_RAW",
    )
    continuity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )

    locations: Mapped[list["RecordingLocation"]] = relationship(
        back_populates="segment",
        cascade="all, delete-orphan",
        lazy="selectin",
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
            name="uq_recording_locations_target_path",
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
        ForeignKey("recording_segments.id", ondelete="CASCADE"),
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
    checksum: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )
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

    segment: Mapped[RecordingSegment] = relationship(
        back_populates="locations",
    )
