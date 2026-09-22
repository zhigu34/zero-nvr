from __future__ import annotations

import uuid
from typing import Literal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


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


class PasswordResetRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)


class PasswordResetRequestAccepted(BaseModel):
    accepted: Literal[True] = True


class PasswordResetCompleteRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=12, max_length=256)


class PasswordResetCompleteView(BaseModel):
    ok: Literal[True] = True


class AuthUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    email_verified: bool
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
    email_verified: bool
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


class UserPasswordResetIssue(BaseModel):
    token: str
    expires_at: datetime


class CameraScopeView(BaseModel):
    mode: Literal["inherit", "all", "selected", "none"]
    camera_ids: list[uuid.UUID] = Field(default_factory=list)
    camera_group_ids: list[uuid.UUID] = Field(default_factory=list)


class CameraScopeUpdate(BaseModel):
    mode: Literal["inherit", "all", "selected", "none"]
    camera_ids: list[uuid.UUID] = Field(default_factory=list)
    camera_group_ids: list[uuid.UUID] = Field(default_factory=list)



class PersonalApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    permissions: list[str] | None = None
    expires_at: datetime | None = None


class PersonalApiTokenView(BaseModel):
    id: uuid.UUID
    name: str
    permissions: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class PersonalApiTokenCreated(PersonalApiTokenView):
    token: str



class OidcProviderCreate(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    issuer: str = Field(min_length=1, max_length=1024)
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: SecretStr
    auto_provision: bool = False
    email_linking: bool = False
    default_role_ids: list[uuid.UUID] = Field(
        default_factory=list
    )


class OidcProviderUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    enabled: bool | None = None
    issuer: str | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
    )
    client_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    client_secret_action: Literal[
        "keep",
        "replace",
        "clear",
    ] = "keep"
    client_secret: SecretStr | None = None
    auto_provision: bool | None = None
    email_linking: bool | None = None
    default_role_ids: list[uuid.UUID] | None = None


class OidcProviderView(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    enabled: bool
    issuer: str
    client_id: str
    client_secret_configured: bool
    auto_provision: bool
    email_linking: bool
    default_role_ids: list[uuid.UUID]



class OidcProviderPublicView(BaseModel):
    key: str
    name: str
