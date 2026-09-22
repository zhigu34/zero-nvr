from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
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


STREAM_PURPOSES = (
    "RECORD",
    "LIVE_HIGH",
    "LIVE_LOW",
    "AI_DETECT",
    "SNAPSHOT",
    "AUDIO",
)


class Device(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        Index("ix_devices_hardware_id", "hardware_id"),
        Index("ix_devices_adapter_type_enabled", "adapter_type", "enabled"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(256), nullable=True)
    hardware_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    adapter_type: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(
        "capabilities",
        JSON,
        nullable=False,
        default=dict,
    )
    capabilities_updated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )

    endpoints: Mapped[list["DeviceEndpoint"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    credentials: Mapped[list["DeviceCredential"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DeviceEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "device_endpoints"
    __table_args__ = (
        Index("ix_device_endpoints_device_enabled", "device_id", "enabled"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    host: Mapped[str] = mapped_column(String(512), nullable=False)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheme: Mapped[str | None] = mapped_column(String(32), nullable=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    device: Mapped[Device] = relationship(back_populates="endpoints")


class DeviceCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "device_credentials"
    __table_args__ = (
        Index("ix_device_credentials_device_kind", "device_id", "kind"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("device_endpoints.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_ref: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("secret_records.id", ondelete="RESTRICT"),
        nullable=False,
    )

    device: Mapped[Device] = relationship(back_populates="credentials")


class DiscoverySession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "discovery_sessions"
    __table_args__ = (
        Index("ix_discovery_sessions_started_at", "started_at"),
    )

    method: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    candidates: Mapped[list["DiscoveryCandidate"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DiscoveryCandidate(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (
        UniqueConstraint(
            "discovery_session_id",
            "candidate_key",
            name="uq_discovery_candidates_session_key",
        ),
    )

    discovery_session_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("discovery_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_key: Mapped[str] = mapped_column(String(512), nullable=False)
    host: Mapped[str | None] = mapped_column(String(512), nullable=True)
    device_identity: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    display_info: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    session: Mapped[DiscoverySession] = relationship(back_populates="candidates")


class Camera(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cameras"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "channel_key",
            name="uq_cameras_device_channel",
        ),
        Index("ix_cameras_enabled_name", "enabled", "name"),
        Index("ix_cameras_retired_at", "retired_at"),
        CheckConstraint(
            "time_sync_mode IN ('monitor','manage_ntp','ignore')",
            name="camera_time_sync_mode",
        ),
        CheckConstraint(
            "config_revision >= 1",
            name="camera_config_revision_positive",
        ),
    )

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=True,
    )
    channel_key: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    maintenance: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    config_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    time_sync_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="monitor",
        server_default="monitor",
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    storage_label: Mapped[str | None] = mapped_column(String(128), nullable=True)

    stream_profiles: Mapped[list["CameraStreamProfile"]] = relationship(
        back_populates="camera",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    stream_bindings: Mapped[list["CameraStreamBinding"]] = relationship(
        back_populates="camera",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CameraStreamProfile(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "camera_stream_profiles"
    __table_args__ = (
        UniqueConstraint(
            "camera_id",
            "adapter_profile_key",
            name="uq_camera_stream_profiles_camera_adapter_key",
        ),
        Index("ix_camera_stream_profiles_camera_status", "camera_id", "status"),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
    )
    adapter_profile_key: Mapped[str] = mapped_column(String(512), nullable=False)
    video_source_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gop_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stream_uri_ref: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("secret_records.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    discovered_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    camera: Mapped[Camera] = relationship(back_populates="stream_profiles")


class CameraStreamBinding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "camera_stream_bindings"
    __table_args__ = (
        UniqueConstraint(
            "camera_id",
            "purpose",
            name="uq_camera_stream_bindings_camera_purpose",
        ),
        CheckConstraint(
            "purpose IN ('RECORD','LIVE_HIGH','LIVE_LOW','AI_DETECT','SNAPSHOT','AUDIO')",
            name="camera_stream_binding_purpose",
        ),
        CheckConstraint(
            "selection_mode IN ('auto','manual')",
            name="camera_stream_binding_selection_mode",
        ),
    )

    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    stream_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("camera_stream_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    selection_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="auto",
    )
    selected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    camera: Mapped[Camera] = relationship(back_populates="stream_bindings")


class CameraGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "camera_groups"

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("camera_groups.id", ondelete="RESTRICT"),
        nullable=True,
    )


class CameraGroupMember(Base):
    __tablename__ = "camera_group_members"

    camera_group_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("camera_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        primary_key=True,
    )


class PrincipalCameraScope(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "principal_camera_scopes"
    __table_args__ = (
        UniqueConstraint(
            "principal_type",
            "principal_id",
            name="uq_principal_camera_scopes_principal",
        ),
        CheckConstraint(
            "principal_type IN ('user','role')",
            name="principal_camera_scope_type",
        ),
        CheckConstraint(
            "scope_mode IN ('all','selected','none')",
            name="principal_camera_scope_mode",
        ),
    )

    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    scope_mode: Mapped[str] = mapped_column(String(16), nullable=False)


class PrincipalCameraScopeEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "principal_camera_scope_entries"
    __table_args__ = (
        CheckConstraint(
            "(camera_id IS NOT NULL AND camera_group_id IS NULL) OR "
            "(camera_id IS NULL AND camera_group_id IS NOT NULL)",
            name="principal_camera_scope_entry_one_target",
        ),
        Index(
            "uq_principal_camera_scope_entries_camera",
            "scope_id",
            "camera_id",
            unique=True,
            sqlite_where=text("camera_id IS NOT NULL"),
            postgresql_where=text("camera_id IS NOT NULL"),
        ),
        Index(
            "uq_principal_camera_scope_entries_group",
            "scope_id",
            "camera_group_id",
            unique=True,
            sqlite_where=text("camera_group_id IS NOT NULL"),
            postgresql_where=text("camera_group_id IS NOT NULL"),
        ),
    )

    scope_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("principal_camera_scopes.id", ondelete="CASCADE"),
        nullable=False,
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=True,
    )
    camera_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("camera_groups.id", ondelete="CASCADE"),
        nullable=True,
    )



class LiveViewLayout(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "live_view_layouts"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "name",
            name="uq_live_view_layouts_owner_name",
        ),
        Index(
            "uq_live_view_layouts_owner_default",
            "owner_user_id",
            unique=True,
            sqlite_where=text("is_default"),
            postgresql_where=text("is_default"),
        ),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    layout_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
