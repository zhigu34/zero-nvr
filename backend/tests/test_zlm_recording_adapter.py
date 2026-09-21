from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.integrations.zlm.recording import (
    ZlmRecordingAdapter,
)


class FakeDelegate:
    instances: list["FakeDelegate"] = []

    def __init__(
        self,
        _settings: Settings,
    ) -> None:
        self.calls: list[tuple] = []
        self.closed = False
        self.__class__.instances.append(self)

    def close(self) -> None:
        self.closed = True

    def is_media_online(
        self,
        *,
        app: str,
        stream: str,
        schema: str,
    ) -> bool:
        self.calls.append(
            (
                "online",
                app,
                stream,
                schema,
            )
        )
        return True

    def is_mp4_recording(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool:
        self.calls.append(
            ("status", app, stream)
        )
        return True

    def start_mp4_recording(
        self,
        *,
        app: str,
        stream: str,
        customized_path: str,
        max_second: int,
    ) -> bool:
        self.calls.append(
            (
                "start",
                app,
                stream,
                customized_path,
                max_second,
            )
        )
        return True

    def stop_mp4_recording(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool:
        self.calls.append(
            ("stop", app, stream)
        )
        return True


def settings(tmp_path: Path) -> Settings:
    return Settings(
        secret_key=(
            "zlm-recording-adapter-test-"
            "secret-key-32-bytes-minimum"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )


def test_recording_adapter_exposes_only_native_recorder_boundary(
    tmp_path: Path,
) -> None:
    FakeDelegate.instances = []

    with ZlmRecordingAdapter(
        settings(tmp_path),
        adapter_factory=FakeDelegate,
    ) as adapter:
        assert adapter.is_stream_online(
            app="zero-nvr",
            stream="profile-test",
        ) is True
        assert adapter.is_recording(
            app="zero-nvr",
            stream="profile-test",
        ) is True
        assert adapter.start(
            app="zero-nvr",
            stream="profile-test",
            customized_path="/recordings",
            max_second=300,
        ) is True
        assert adapter.stop(
            app="zero-nvr",
            stream="profile-test",
        ) is True

    assert len(FakeDelegate.instances) == 1
    delegate = FakeDelegate.instances[0]
    assert delegate.calls == [
        (
            "online",
            "zero-nvr",
            "profile-test",
            "rtsp",
        ),
        (
            "status",
            "zero-nvr",
            "profile-test",
        ),
        (
            "start",
            "zero-nvr",
            "profile-test",
            "/recordings",
            300,
        ),
        (
            "stop",
            "zero-nvr",
            "profile-test",
        ),
    ]
    assert delegate.closed is True
