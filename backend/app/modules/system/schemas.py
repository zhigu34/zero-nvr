from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class FrigateCameraMapping(BaseModel):
    frigate_camera: str = Field(
        min_length=1,
        max_length=256,
    )
    camera_id: uuid.UUID


class FrigateCredentialsInput(BaseModel):
    http_bearer_token: SecretStr | None = None
    http_username: SecretStr | None = None
    http_password: SecretStr | None = None
    mqtt_username: SecretStr | None = None
    mqtt_password: SecretStr | None = None


class FrigateProviderPut(BaseModel):
    enabled: bool = False
    mode: Literal["managed", "external"] = "external"
    base_url: str
    camera_map: list[FrigateCameraMapping] = Field(
        default_factory=list
    )
    mqtt_enabled: bool = False
    mqtt_host: str | None = None
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_topic_prefix: str = Field(
        default="frigate",
        min_length=1,
        max_length=128,
    )
    mqtt_tls: bool = False
    credentials: FrigateCredentialsInput | None = None
    replace_credentials: bool = False


class FrigateProviderView(BaseModel):
    configured: bool = True
    enabled: bool
    mode: Literal["managed", "external"]
    instance_id: str
    base_url: str
    camera_map: list[FrigateCameraMapping]
    mqtt_enabled: bool
    mqtt_host: str | None
    mqtt_port: int
    mqtt_topic_prefix: str
    mqtt_tls: bool
    credentials_configured: bool


class FrigateProviderTestView(BaseModel):
    ok: bool = True
    version: str | None = None


class FrigateBackfillRequest(BaseModel):
    lookback_seconds: int = Field(
        default=600,
        ge=60,
        le=86400,
    )


class FrigateBackfillQueuedView(BaseModel):
    queued: bool = True
    lookback_seconds: int
