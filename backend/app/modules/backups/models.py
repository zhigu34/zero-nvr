from __future__ import annotations

import uuid
from datetime import datetime

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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import UTCDateTime, UUIDType, utc_now


class BackupPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "backup_policies"
    __table_args__ = (
        CheckConstraint(
            "database_backend IN ('sqlite','postgresql')",
            name="backup_policy_database_backend",
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
    repository_config_ref: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("secret_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    credential_secret_ref: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("secret_records.id", ondelete="RESTRICT"),
        nullable=True,
    )
    database_backend: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    schedule_json: Mapped[dict[str, object]] = mapped_column(
        "schedule",
        JSON,
        nullable=False,
        default=dict,
    )
    retention_policy_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    verify_after_backup: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    repository_check_schedule_json: Mapped[
        dict[str, object]
    ] = mapped_column(
        "repository_check_schedule",
        JSON,
        nullable=False,
        default=dict,
    )
    include_deployment_config: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )


class BackupSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "backup_sets"
    __table_args__ = (
        UniqueConstraint(
            "backup_policy_id",
            "schedule_slot",
            name="uq_backup_sets_policy_schedule_slot",
        ),
        Index(
            "ix_backup_sets_policy_started",
            "backup_policy_id",
            "started_at",
        ),
        Index(
            "ix_backup_sets_state_started",
            "state",
            "started_at",
        ),
        CheckConstraint(
            "state IN ('PENDING','RUNNING','COMPLETED','FAILED')",
            name="backup_set_state",
        ),
        CheckConstraint(
            "verification_state IN ('PENDING','PASSED','FAILED','SKIPPED')",
            name="backup_set_verification_state",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="backup_set_size_nonnegative",
        ),
    )

    backup_policy_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("backup_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PENDING",
    )
    reason: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    schedule_slot: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    app_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    schema_revision: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    database_engine: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    restic_snapshot_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    verification_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PENDING",
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    sanitized_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
