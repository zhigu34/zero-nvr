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



class GeneralSystemSettingsView(BaseModel):
    system_name: str
    display_timezone: str
    camera_ntp_servers: list[str]


class GeneralSystemSettingsPatch(BaseModel):
    system_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    display_timezone: str | None = None
    camera_ntp_servers: list[str] | None = None


class SystemSettingsView(BaseModel):
    general: GeneralSystemSettingsView


class SystemSettingsPatch(BaseModel):
    general: GeneralSystemSettingsPatch | None = None


class SystemUpdateInfoView(BaseModel):
    current_version: str
    latest_version: str | None = None
    status: Literal["unknown", "current", "update_available"] = "unknown"
    deployment_method: Literal["deploy.sh"] = "deploy.sh"
    automatic_host_mutation: bool = False
    update_command: str = "./deploy.sh update"



class HealthComponentView(BaseModel):
    status: Literal["OK", "DEGRADED", "ERROR", "DISABLED"]
    message: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class SystemHealthView(BaseModel):
    status: Literal["OK", "DEGRADED", "ERROR", "DISABLED"]
    components: dict[str, HealthComponentView]



class CameraNtpDeviceResultView(BaseModel):
    device_id: uuid.UUID
    name: str
    status: Literal["UPDATED", "FAILED"]
    error_code: str | None = None


class CameraNtpApplyView(BaseModel):
    mode: Literal["manual", "dhcp"]
    total_devices: int
    updated: int
    failed: int
    results: list[CameraNtpDeviceResultView]
