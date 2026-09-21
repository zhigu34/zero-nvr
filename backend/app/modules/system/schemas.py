from __future__ import annotations

import uuid
from datetime import datetime
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


class RuntimeTuningSettingsView(BaseModel):
    prebuffer_fragment_seconds: int
    prebuffer_buffer_seconds: int
    playback_cache_max_bytes: int
    playback_cache_ttl_seconds: int
    playback_restore_lock_ttl_seconds: int
    live_transcode_max_derivatives: int
    live_transcode_idle_ttl_seconds: int
    live_transcode_lease_ttl_seconds: int
    live_transcode_startup_timeout_seconds: float
    live_transcode_cpu_threads: int
    live_transcode_video_bitrate_kbps: int


class RuntimeTuningSettingsPatch(BaseModel):
    prebuffer_fragment_seconds: int | None = Field(
        default=None,
        ge=2,
        le=30,
    )
    prebuffer_buffer_seconds: int | None = Field(
        default=None,
        ge=10,
        le=600,
    )
    playback_cache_max_bytes: int | None = Field(
        default=None,
        ge=64 * 1024 * 1024,
        le=1024 * 1024 * 1024 * 1024,
    )
    playback_cache_ttl_seconds: int | None = Field(
        default=None,
        ge=60,
        le=7 * 24 * 60 * 60,
    )
    playback_restore_lock_ttl_seconds: int | None = Field(
        default=None,
        ge=60,
        le=7 * 24 * 60 * 60,
    )
    live_transcode_max_derivatives: int | None = Field(
        default=None,
        ge=1,
        le=8,
    )
    live_transcode_idle_ttl_seconds: int | None = Field(
        default=None,
        ge=5,
        le=300,
    )
    live_transcode_lease_ttl_seconds: int | None = Field(
        default=None,
        ge=15,
        le=300,
    )
    live_transcode_startup_timeout_seconds: float | None = Field(
        default=None,
        ge=1,
        le=30,
    )
    live_transcode_cpu_threads: int | None = Field(
        default=None,
        ge=1,
        le=8,
    )
    live_transcode_video_bitrate_kbps: int | None = Field(
        default=None,
        ge=512,
        le=20000,
    )


class SystemSettingsView(BaseModel):
    general: GeneralSystemSettingsView
    runtime: RuntimeTuningSettingsView


class SystemSettingsPatch(BaseModel):
    general: GeneralSystemSettingsPatch | None = None
    runtime: RuntimeTuningSettingsPatch | None = None


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



class CameraClockHealthResultView(BaseModel):
    device_id: uuid.UUID
    name: str
    status: Literal["OK", "DEGRADED", "ERROR"]
    date_time_type: str | None = None
    timezone: str | None = None
    camera_utc_at: datetime | None = None
    offset_ms: int | None = None
    rtt_ms: int | None = None
    error_code: str | None = None


class CameraClockHealthView(BaseModel):
    status: Literal["OK", "DEGRADED", "ERROR", "DISABLED"]
    checked_at: datetime
    total_devices: int
    ok: int
    degraded: int
    error: int
    results: list[CameraClockHealthResultView]



class ConfigurationImportValidateRequest(BaseModel):
    bundle: dict[str, object]


class ConfigurationCredentialRequirementView(BaseModel):
    section: str
    resource_type: str
    resource_id: str | None = None
    name: str | None = None
    credential: str


class ConfigurationImportValidationView(BaseModel):
    valid: Literal[True] = True
    format: Literal["zero-nvr.configuration"] = "zero-nvr.configuration"
    format_version: Literal[1] = 1
    source_application_version: str | None = None
    section_counts: dict[str, int]
    credentials_required: list[
        ConfigurationCredentialRequirementView
    ]
    warnings: list[str]



class ConfigurationImportApplyRequest(BaseModel):
    bundle: dict[str, object]


class ConfigurationImportApplyItemView(BaseModel):
    section: str
    resource_type: str
    source_id: str | None = None
    target_id: str | None = None
    name: str | None = None
    action: Literal[
        "created",
        "updated",
        "matched",
        "skipped",
    ]
    reason: str | None = None


class ConfigurationImportApplyView(BaseModel):
    mode: Literal["merge"] = "merge"
    applied_count: int
    skipped_count: int
    applied: list[
        ConfigurationImportApplyItemView
    ]
    skipped: list[
        ConfigurationImportApplyItemView
    ]
    warnings: list[str]



class ReleaseValidationArtifactView(BaseModel):
    kind: Literal["benchmark", "soak"]
    state: Literal[
        "AVAILABLE",
        "MISSING",
        "INVALID",
    ]
    command: str
    updated_at: datetime | None = None
    report: dict[str, object] | None = None
    error_code: str | None = None


class ReleaseValidationView(BaseModel):
    benchmark: ReleaseValidationArtifactView
    soak: ReleaseValidationArtifactView


class ReleaseReadinessCheckView(BaseModel):
    name: Literal[
        "benchmark",
        "soak",
        "verified_backup",
    ]
    passed: bool
    code: str
    details: dict[str, object]


class ReleaseReadinessView(BaseModel):
    expected_cameras: Literal[8, 16]
    checked_at: datetime
    max_age_hours: int
    passed: bool
    checks: list[ReleaseReadinessCheckView]
