from __future__ import annotations

import uuid
from typing import Literal
from datetime import datetime

from pydantic import BaseModel, Field, SecretStr


class BackupCredentialsInput(BaseModel):
    password: SecretStr
    environment: dict[str, SecretStr] = Field(
        default_factory=dict
    )


class BackupPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    repository: SecretStr
    credentials: BackupCredentialsInput
    initialize_if_missing: bool = False
    database_backend: str
    schedule: dict[str, object] = Field(
        default_factory=dict
    )
    retention: dict[str, object] = Field(
        default_factory=dict
    )
    verify_after_backup: bool = True
    repository_check_schedule: dict[str, object] = Field(
        default_factory=dict
    )
    include_deployment_config: bool = False


class BackupCredentialsUpdate(BaseModel):
    password: SecretStr | None = None
    environment: dict[str, SecretStr] | None = None


class BackupPolicyUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    enabled: bool | None = None
    repository: SecretStr | None = None
    credentials_action: Literal[
        "keep",
        "replace",
        "clear",
    ] = "keep"
    credentials: BackupCredentialsUpdate | None = None
    initialize_if_missing: bool | None = None
    schedule: dict[str, object] | None = None
    retention: dict[str, object] | None = None
    verify_after_backup: bool | None = None
    repository_check_schedule: dict[str, object] | None = None
    include_deployment_config: bool | None = None


class BackupPolicyView(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    database_backend: str
    schedule: dict[str, object]
    retention: dict[str, object]
    verify_after_backup: bool
    repository_check_schedule: dict[str, object]
    include_deployment_config: bool
    repository_configured: bool
    credentials_configured: bool


class BackupRunRequest(BaseModel):
    policy_id: uuid.UUID
    reason: Literal[
        "manual",
        "pre_upgrade",
        "pre_restore",
        "pre_database_migration",
    ] = "manual"


class BackupSetView(BaseModel):
    id: uuid.UUID
    backup_policy_id: uuid.UUID
    state: str
    reason: str
    started_at: datetime
    completed_at: datetime | None
    app_version: str
    schema_revision: str
    database_engine: str
    restic_snapshot_id: str | None
    size_bytes: int | None
    verification_state: str
    last_verified_at: datetime | None
    error_code: str | None
    sanitized_error: str | None
    created_at: datetime



class BackupSetPage(BaseModel):
    items: list[BackupSetView]
    next_cursor: str | None
