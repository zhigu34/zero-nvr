from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class StorageTargetCreate(BaseModel):
    type: Literal["local", "rclone"]
    role: Literal["recording", "archive"]
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    config: dict[str, object] = Field(default_factory=dict)
    rclone_config: SecretStr | None = None


class StorageTargetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    config: dict[str, object] | None = None
    rclone_config: SecretStr | None = None


class StorageTargetView(BaseModel):
    id: uuid.UUID
    type: Literal["local", "rclone"]
    role: Literal["recording", "archive"]
    name: str
    enabled: bool
    config: dict[str, object]
    credentials_configured: bool


class StorageTargetRecordingSwitchRequest(BaseModel):
    destination_target_id: uuid.UUID


class StorageTargetRecordingSwitchView(BaseModel):
    source_target_id: uuid.UUID
    destination_target_id: uuid.UUID
    explicit_policies_updated: int
    implicit_policies_rebound: int
    default_moved: bool
    affected_camera_ids: list[uuid.UUID]


class StorageTargetTestView(BaseModel):
    ok: bool = True
    type: Literal["local", "rclone"]
    detail: str
    free_bytes: int | None = None
    total_bytes: int | None = None
    used_bytes: int | None = None
    used_percent: float | None = None
    capacity_level: Literal[
        "normal",
        "warning",
        "high",
        "critical",
    ] | None = None
    warning_percent: int | None = None
    high_percent: int | None = None
    critical_percent: int | None = None



class RetentionPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scope_type: Literal["GLOBAL", "CAMERA", "CAMERA_GROUP"]
    scope_id: uuid.UUID | None = None
    ordinary_keep_days: int = Field(ge=0, le=36500)
    event_keep_days: int = Field(ge=0, le=36500)
    manual_keep_days: int = Field(ge=0, le=36500)
    mode: Literal["BEST_EFFORT", "HARD"]
    require_archive_before_delete: bool = True
    enabled: bool = True


class RetentionPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    scope_type: Literal["GLOBAL", "CAMERA", "CAMERA_GROUP"] | None = None
    scope_id: uuid.UUID | None = None
    ordinary_keep_days: int | None = Field(default=None, ge=0, le=36500)
    event_keep_days: int | None = Field(default=None, ge=0, le=36500)
    manual_keep_days: int | None = Field(default=None, ge=0, le=36500)
    mode: Literal["BEST_EFFORT", "HARD"] | None = None
    require_archive_before_delete: bool | None = None
    enabled: bool | None = None


class RetentionPolicyView(BaseModel):
    id: uuid.UUID
    name: str
    scope_type: Literal["GLOBAL", "CAMERA", "CAMERA_GROUP"]
    scope_id: uuid.UUID | None
    ordinary_keep_days: int
    event_keep_days: int
    manual_keep_days: int
    mode: Literal["BEST_EFFORT", "HARD"]
    require_archive_before_delete: bool
    enabled: bool
