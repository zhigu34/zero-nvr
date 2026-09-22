from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


class ManualRtspStreamInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    rtsp_url: SecretStr


class CameraCreate(BaseModel):
    mode: Literal["manual_rtsp"] = "manual_rtsp"
    name: str = Field(min_length=1, max_length=128)
    location: str | None = Field(default=None, max_length=256)
    storage_label: str | None = Field(default=None, max_length=128)
    primary_stream: ManualRtspStreamInput
    secondary_stream: ManualRtspStreamInput | None = None


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    location: str | None = Field(default=None, max_length=256)
    storage_label: str | None = Field(default=None, max_length=128)
    maintenance: bool | None = None
    time_sync_mode: Literal[
        "monitor",
        "manage_ntp",
        "ignore",
    ] | None = None


class CameraClockProjectionView(BaseModel):
    camera_id: uuid.UUID
    device_id: uuid.UUID | None
    health: Literal[
        "unknown",
        "healthy",
        "warning",
        "critical",
        "unsupported",
    ]
    quality: Literal[
        "unknown",
        "good",
        "degraded",
        "poor",
    ]
    sync_mode: Literal[
        "monitor",
        "manage_ntp",
        "ignore",
    ]
    measured_at: datetime | None = None
    offset_ms: int | None = None
    uncertainty_ms: int | None = None
    rtt_ms: int | None = None
    device_timezone: str | None = None
    device_time_source: str | None = None
    error_code: str | None = None


class CameraSummary(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    maintenance: bool
    retired_at: datetime | None
    location: str | None
    storage_label: str | None
    adapter_type: str | None
    time_sync_mode: Literal[
        "monitor",
        "manage_ntp",
        "ignore",
    ]
    ptz_capable: bool = False


class CameraGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2048)
    parent_id: uuid.UUID | None = None
    camera_ids: list[uuid.UUID] = Field(default_factory=list)


class CameraGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2048)
    parent_id: uuid.UUID | None = None
    camera_ids: list[uuid.UUID] | None = None


class CameraGroupView(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    camera_ids: list[uuid.UUID]


class CameraStreamProfileView(BaseModel):
    id: uuid.UUID
    name: str
    adapter_profile_key: str
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    bitrate_kbps: int | None
    gop_seconds: float | None
    audio_codec: str | None
    has_audio: bool
    status: str
    last_verified_at: datetime | None


class CameraStreamBindingView(BaseModel):
    purpose: str
    stream_profile_id: uuid.UUID
    selection_mode: Literal["auto", "manual"]


class CameraDetail(CameraSummary):
    streams: list[CameraStreamProfileView]
    bindings: list[CameraStreamBindingView]


class CameraStreamBindingInput(BaseModel):
    purpose: Literal[
        "RECORD",
        "LIVE_HIGH",
        "LIVE_LOW",
        "AI_DETECT",
        "SNAPSHOT",
        "AUDIO",
    ]
    stream_profile_id: uuid.UUID
    selection_mode: Literal["auto", "manual"] = "manual"


class CameraStreamBindingsUpdate(BaseModel):
    bindings: list[CameraStreamBindingInput]


class CameraProbeTrackView(BaseModel):
    kind: Literal["video", "audio"]
    codec: str | None
    ready: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    gop_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None


class CameraStreamDiagnosticView(BaseModel):
    profile: CameraStreamProfileView
    video: CameraProbeTrackView | None
    audio: CameraProbeTrackView | None
    verified_at: datetime


class CameraProbeStreamView(BaseModel):
    role: Literal["primary", "secondary"]
    name: str
    video: CameraProbeTrackView | None
    audio: CameraProbeTrackView | None


class CameraProbeResult(BaseModel):
    ok: Literal[True] = True
    streams: list[CameraProbeStreamView]


class DiscoveryCandidateView(BaseModel):
    id: uuid.UUID
    candidate_key: str
    host: str | None
    port: int | None
    device_service_url: str | None
    display_info: dict[str, object]
    state: str


class DiscoverySessionView(BaseModel):
    id: uuid.UUID
    method: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    candidates: list[DiscoveryCandidateView]


class OnvifCameraTestInput(BaseModel):
    host: str = Field(min_length=1, max_length=512)
    port: int = Field(default=80, ge=1, le=65535)
    username: str = Field(default="", max_length=128)
    password: SecretStr

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or "://" in normalized
            or "/" in normalized
            or "@" in normalized
            or any(char.isspace() for char in normalized)
        ):
            raise ValueError("host must be a hostname or IP address")
        return normalized


class OnvifDeviceInfoView(BaseModel):
    manufacturer: str | None
    model: str | None
    firmware_version: str | None
    serial_number: str | None
    hardware_id: str | None


class OnvifProfileView(BaseModel):
    token: str
    name: str
    video_source_token: str | None
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    bitrate_kbps: int | None
    gop_seconds: float | None
    audio_codec: str | None
    has_audio: bool
    stream_uri_available: bool


class OnvifInspectionView(BaseModel):
    device: OnvifDeviceInfoView
    capabilities: list[str]
    profiles: list[OnvifProfileView]


class OnvifCameraImportInput(OnvifCameraTestInput):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    location: str | None = Field(default=None, max_length=256)
    storage_label: str | None = Field(default=None, max_length=128)
    profile_tokens: list[str] | None = None
    discovery_candidate_id: uuid.UUID | None = None


class OnvifImportResult(BaseModel):
    device_id: uuid.UUID
    reconfigured: bool = False
    cameras: list[CameraDetail]


class CameraLiveStreamView(BaseModel):
    camera_id: uuid.UUID
    profile_id: uuid.UUID
    purpose: Literal["LIVE_HIGH", "LIVE_LOW", "RECORD"]
    transport: Literal["hls"] = "hls"
    transports: list[
        Literal["webrtc", "hls"]
    ] = Field(
        default_factory=lambda: [
            "webrtc",
            "hls",
        ]
    )
    hls_url: str
    media_session_id: uuid.UUID
    expires_at: datetime
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool
    compatibility: Literal[
        "h264_transcode"
    ] | None = None
    compatibility_lease_id: uuid.UUID | None = None
    compatibility_acceleration: Literal[
        "cpu",
        "nvenc",
        "vaapi",
    ] | None = None



class CameraIceServerView(BaseModel):
    urls: list[str]
    username: str
    credential: str
    expires_at: datetime


class CameraIceServersView(BaseModel):
    enabled: bool
    ice_servers: list[
        CameraIceServerView
    ] = Field(default_factory=list)


class CameraPtzMove(BaseModel):
    pan: float = Field(default=0.0, ge=-1.0, le=1.0)
    tilt: float = Field(default=0.0, ge=-1.0, le=1.0)
    zoom: float = Field(default=0.0, ge=-1.0, le=1.0)


class CameraPtzActionView(BaseModel):
    ok: Literal[True] = True
