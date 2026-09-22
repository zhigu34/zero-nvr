from __future__ import annotations

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
        **kwargs: Any,
    ) -> Any: ...

    async def configure_ntp(
        self,
        **kwargs: Any,
    ) -> None: ...

    async def ptz_move(
        self,
        **kwargs: Any,
    ) -> None: ...

    async def ptz_stop(
        self,
        **kwargs: Any,
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
        schema: str | None = None,
    ) -> bool: ...

    def add_stream_proxy(
        self,
        **kwargs: Any,
    ) -> str: ...

    def delete_stream_proxy(
        self,
        key: str,
    ) -> None: ...

    def close_stream(
        self,
        **kwargs: Any,
    ) -> bool: ...

    def snapshot(
        self,
        **kwargs: Any,
    ) -> bytes: ...

    def whep_play(
        self,
        **kwargs: Any,
    ) -> Any: ...

    def delete_webrtc(
        self,
        **kwargs: Any,
    ) -> None: ...

    def load_mp4_file(
        self,
        **kwargs: Any,
    ) -> Any: ...

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
        **kwargs: Any,
    ) -> None: ...

    def copy_to_local(
        self,
        **kwargs: Any,
    ) -> None: ...

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
        **kwargs: Any,
    ) -> list[dict[str, Any]]: ...

    def snapshot(
        self,
        camera: str,
        **kwargs: Any,
    ) -> bytes: ...


@runtime_checkable
class IntegrationAdapter(Protocol):
    def capabilities(self) -> Any: ...

    def enable(self) -> None: ...

    def disable(self) -> None: ...

    def status(self) -> Any: ...
