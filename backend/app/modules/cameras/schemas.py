from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


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


class CameraSummary(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    location: str | None
    storage_label: str | None
    adapter_type: str | None


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
