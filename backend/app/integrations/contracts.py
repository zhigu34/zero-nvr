from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Self, runtime_checkable


@runtime_checkable
class DeviceAdapter(Protocol):
    async def discover(self) -> list[Any]: ...

    async def inspect_device(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> Any: ...

    async def read_system_clock(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> Any: ...

    async def configure_ntp(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        servers: tuple[str, ...],
    ) -> None: ...

    async def ptz_move(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        preferred_profile_tokens: tuple[str, ...] = (),
        pan: float = 0.0,
        tilt: float = 0.0,
        zoom: float = 0.0,
    ) -> None: ...

    async def ptz_stop(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        preferred_profile_tokens: tuple[str, ...] = (),
    ) -> None: ...


@runtime_checkable
class MediaPlane(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        *_exc: object,
    ) -> None: ...

    def is_media_online(
        self,
        *,
        app: str,
        stream: str,
        schema: str = "rtsp",
    ) -> bool: ...

    def wait_media_online(
        self,
        *,
        app: str,
        stream: str,
        timeout_seconds: float,
        schema: str = "rtsp",
    ) -> bool: ...

    def add_stream_proxy(
        self,
        *,
        app: str,
        stream: str,
        source_url: str,
        enable_mp4: bool = False,
        enable_hls: bool = False,
        mp4_save_path: str | None = None,
        mp4_max_second: int | None = None,
        retry_count: int = -1,
        auto_close: bool = False,
        mp4_as_player: bool = False,
    ) -> str: ...

    def delete_stream_proxy(
        self,
        key: str,
    ) -> None: ...

    def close_stream(
        self,
        *,
        app: str,
        stream: str,
        schema: str = "rtsp",
        force: bool = True,
    ) -> bool: ...

    def snapshot(
        self,
        *,
        source_url: str,
        timeout_seconds: int = 10,
        expire_seconds: int = 3,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> tuple[bytes, str]: ...

    def whep_play(
        self,
        *,
        app: str,
        stream: str,
        offer_sdp: str,
        playback_params: dict[str, str],
        preferred_tcp: bool = False,
        candidate_udp: str | None = None,
        candidate_tcp: str | None = None,
        max_sdp_bytes: int = 256 * 1024,
    ) -> Any: ...

    def delete_webrtc(
        self,
        *,
        session_id: str,
        session_token: str,
    ) -> None: ...

    def load_mp4_file(
        self,
        *,
        app: str,
        stream: str,
        file_path: str,
        seek_ms: int = 0,
        speed: float = 1.0,
    ) -> bool: ...

    def probe_rtsp_source(
        self,
        source_url: str,
    ) -> Any: ...


@runtime_checkable
class RecordingBackend(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        *_exc: object,
    ) -> None: ...

    def is_stream_online(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool: ...

    def is_recording(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool: ...

    def start(
        self,
        *,
        app: str,
        stream: str,
        customized_path: str,
        max_second: int,
    ) -> bool: ...

    def stop(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool: ...


@runtime_checkable
class StorageBackend(Protocol):
    def copy_to_remote(
        self,
        *,
        source: Path,
        destination: str,
        expected_size: int,
    ) -> Any: ...

    def copy_to_local(
        self,
        *,
        source: str,
        destination: Path,
        expected_size: int | None = None,
    ) -> Any: ...

    def stat(
        self,
        remote_path: str,
    ) -> Any: ...

    def delete_file(
        self,
        remote_path: str,
    ) -> None: ...


@runtime_checkable
class NotificationBackend(Protocol):
    def notify(
        self,
        *,
        title: str,
        body: str,
        notify_type: str = "info",
    ) -> None: ...


@runtime_checkable
class EmailBackend(Protocol):
    def test_connection(self) -> None: ...

    def send_email(
        self,
        *,
        recipient: str,
        title: str,
        body: str,
    ) -> None: ...


@runtime_checkable
class DetectionProvider(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        *_exc: object,
    ) -> None: ...

    def version(self) -> Any: ...

    def events(
        self,
        *,
        after: float | None = None,
        before: float | None = None,
        cameras: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    def snapshot(
        self,
        event_id: str,
        *,
        clean: bool = False,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> tuple[bytes, str]: ...


@runtime_checkable
class IntegrationAdapter(Protocol):
    def capabilities(self) -> Any: ...

    def enable(self) -> None: ...

    def disable(self) -> None: ...

    def status(self) -> Any: ...
