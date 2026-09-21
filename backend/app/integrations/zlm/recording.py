from __future__ import annotations

from typing import Any, Callable

from app.core.config import Settings

from .adapter import ZlmAdapter


class ZlmRecordingAdapter:
    """Narrow ZLMediaKit boundary for the native MP4 recorder.

    RecordingRuntimeService depends only on this interface instead of the
    general media-plane adapter. ZLM remains the recorder authority; this
    class only forwards start/stop/status/stream-online control.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        adapter_factory: Callable[
            [Settings],
            Any,
        ] = ZlmAdapter,
    ) -> None:
        self._delegate = adapter_factory(settings)

    def close(self) -> None:
        self._delegate.close()

    def __enter__(self) -> "ZlmRecordingAdapter":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def is_stream_online(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool:
        return self._delegate.is_media_online(
            app=app,
            stream=stream,
            schema="rtsp",
        )

    def is_recording(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool:
        return self._delegate.is_mp4_recording(
            app=app,
            stream=stream,
        )

    def start(
        self,
        *,
        app: str,
        stream: str,
        customized_path: str,
        max_second: int,
    ) -> bool:
        return self._delegate.start_mp4_recording(
            app=app,
            stream=stream,
            customized_path=customized_path,
            max_second=max_second,
        )

    def stop(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool:
        return self._delegate.stop_mp4_recording(
            app=app,
            stream=stream,
        )
