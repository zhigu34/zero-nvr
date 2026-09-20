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


class StorageTargetTestView(BaseModel):
    ok: bool = True
    type: Literal["local", "rclone"]
    detail: str
    free_bytes: int | None = None
