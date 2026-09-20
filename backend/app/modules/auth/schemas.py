from __future__ import annotations

import uuid
from typing import Literal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SetupStatus(BaseModel):
    requires_initial_admin: bool


class InitialAdministratorCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    email: EmailStr | None = None
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class AuthUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    roles: list[str]
    permissions: list[str]


class SessionSummary(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool
    client_info: dict[str, object] | None


class RoleSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    built_in: bool


class RoleView(RoleSummary):
    permissions: list[str]


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2048)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2048)
    permissions: list[str] | None = None


class UserAdminView(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    enabled: bool
    roles: list[RoleSummary]


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    email: EmailStr | None = None
    password: str = Field(min_length=12, max_length=256)
    role_ids: list[uuid.UUID] = Field(default_factory=list)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: EmailStr | None = None
    role_ids: list[uuid.UUID] | None = None


class UserPasswordReset(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)


class CameraScopeView(BaseModel):
    mode: Literal["inherit", "all", "selected", "none"]
    camera_ids: list[uuid.UUID] = Field(default_factory=list)
    camera_group_ids: list[uuid.UUID] = Field(default_factory=list)


class CameraScopeUpdate(BaseModel):
    mode: Literal["inherit", "all", "selected", "none"]
    camera_ids: list[uuid.UUID] = Field(default_factory=list)
    camera_group_ids: list[uuid.UUID] = Field(default_factory=list)
