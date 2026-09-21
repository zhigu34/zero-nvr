from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.live_transcode import (
    LiveTranscodeError,
    LiveTranscodeManager,
)
from app.modules.system.settings import (
    RuntimeTuningSettingsService,
)


class FakeProcess:
    def __init__(
        self,
        *,
        returncode: int | None = None,
    ) -> None:
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeTimer:
    created: list["FakeTimer"] = []

    def __init__(
        self,
        seconds,
        callback,
        args=(),
    ) -> None:
        self.seconds = seconds
        self.callback = callback
        self.args = args
        self.cancelled = False
        self.started = False
        self.daemon = False
        self.created.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback(*self.args)


class FakeZlm:
    def __init__(self, _settings) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def is_media_online(
        self,
        *,
        app: str,
        stream: str,
        schema: str = "rtsp",
    ) -> bool:
        assert app == "zero-nvr-compat"
        assert stream.startswith("h264-")
        assert schema == "rtmp"
        return True


class FakeCompleted:
    def __init__(self, output: str = "") -> None:
        self.stdout = output
        self.stderr = ""
        self.returncode = 0


def settings(
    tmp_path: Path,
    **overrides,
) -> Settings:
    values = {
        "secret_key": (
            "live-transcode-test-secret-key-"
            "32-bytes-minimum"
        ),
        "environment": "test",
        "data_dir": tmp_path / "data",
        "cache_dir": tmp_path / "cache",
        "live_transcode_idle_ttl_seconds": 5,
        "live_transcode_lease_ttl_seconds": 15,
        "live_transcode_startup_timeout_seconds": 1,
        "live_transcode_cpu_threads": 2,
    }
    values.update(overrides)
    return Settings(**values)


def test_shared_derivative_uses_separate_leases_and_idle_cleanup(
    tmp_path: Path,
) -> None:
    FakeTimer.created = []
    commands: list[list[str]] = []
    processes: list[FakeProcess] = []

    def popen(command, **_kwargs):
        commands.append(command)
        process = FakeProcess()
        processes.append(process)
        return process

    manager = LiveTranscodeManager(
        settings(tmp_path),
        popen_factory=popen,
        run_factory=lambda *_args, **_kwargs: FakeCompleted(),
        zlm_factory=FakeZlm,
        timer_factory=FakeTimer,
    )
    camera_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    internal_source = (
        "rtsp://zlmediakit:554/zero-nvr/"
        f"profile-{profile_id.hex}"
    )

    first = manager.acquire(
        camera_id=camera_id,
        owner_user_id=owner_user_id,
        profile_id=profile_id,
        source_url=internal_source,
        has_audio=True,
    )
    second = manager.acquire(
        camera_id=camera_id,
        owner_user_id=owner_user_id,
        profile_id=profile_id,
        source_url=internal_source,
        has_audio=True,
    )

    assert first.lease_id != second.lease_id
    assert first.reference == second.reference
    assert not manager.touch(
        first.lease_id,
        camera_id=camera_id,
        owner_user_id=uuid.uuid4(),
    )
    assert manager.touch(
        first.lease_id,
        camera_id=camera_id,
        owner_user_id=owner_user_id,
    )
    assert first.acceleration == "cpu"
    assert len(commands) == 1
    assert len(processes) == 1
    assert internal_source in commands[0]
    assert "rtmp://zlmediakit:1935/zero-nvr-compat/" in (
        " ".join(commands[0])
    )
    assert "libx264" in commands[0]
    assert "-threads" in commands[0]
    assert commands[0][
        commands[0].index("-threads") + 1
    ] == "2"

    assert manager.release(
        first.lease_id,
        camera_id=camera_id,
        owner_user_id=owner_user_id,
    )
    assert not processes[0].terminated

    assert manager.release(
        second.lease_id,
        camera_id=camera_id,
        owner_user_id=owner_user_id,
    )
    idle = [
        timer
        for timer in FakeTimer.created
        if (
            timer.callback.__name__
            == "_expire_derivative"
            and not timer.cancelled
        )
    ]
    assert len(idle) == 1
    idle[0].fire()
    assert processes[0].terminated


def test_capacity_refuses_second_active_derivative(
    tmp_path: Path,
) -> None:
    FakeTimer.created = []
    manager = LiveTranscodeManager(
        settings(
            tmp_path,
            live_transcode_max_derivatives=1,
        ),
        popen_factory=lambda *_args, **_kwargs: FakeProcess(),
        run_factory=lambda *_args, **_kwargs: FakeCompleted(),
        zlm_factory=FakeZlm,
        timer_factory=FakeTimer,
    )
    camera_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    first_profile = uuid.uuid4()
    second_profile = uuid.uuid4()

    manager.acquire(
        camera_id=camera_id,
        owner_user_id=owner_user_id,
        profile_id=first_profile,
        source_url=(
            "rtsp://zlmediakit:554/zero-nvr/"
            f"profile-{first_profile.hex}"
        ),
        has_audio=False,
    )

    with pytest.raises(
        LiveTranscodeError
    ) as captured:
        manager.acquire(
            camera_id=camera_id,
            owner_user_id=owner_user_id,
            profile_id=second_profile,
            source_url=(
                "rtsp://zlmediakit:554/zero-nvr/"
                f"profile-{second_profile.hex}"
            ),
            has_audio=False,
        )

    assert (
        captured.value.code
        == "live_transcode_capacity"
    )
    manager.stop()


def test_hardware_failure_falls_back_to_bounded_cpu(
    tmp_path: Path,
) -> None:
    FakeTimer.created = []
    commands: list[list[str]] = []
    processes = [
        FakeProcess(returncode=1),
        FakeProcess(),
    ]

    def popen(command, **_kwargs):
        commands.append(command)
        return processes[len(commands) - 1]

    manager = LiveTranscodeManager(
        settings(tmp_path),
        popen_factory=popen,
        run_factory=lambda *_args, **_kwargs: FakeCompleted(
            " V..... h264_nvenc NVIDIA NVENC H.264 encoder"
        ),
        zlm_factory=FakeZlm,
        timer_factory=FakeTimer,
        path_exists=lambda path: path == "/dev/nvidia0",
    )
    camera_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    profile_id = uuid.uuid4()

    lease = manager.acquire(
        camera_id=camera_id,
        owner_user_id=owner_user_id,
        profile_id=profile_id,
        source_url=(
            "rtsp://zlmediakit:554/zero-nvr/"
            f"profile-{profile_id.hex}"
        ),
        has_audio=False,
    )

    assert lease.acceleration == "cpu"
    assert len(commands) == 2
    assert "h264_nvenc" in commands[0]
    assert "libx264" in commands[1]
    assert "-threads" in commands[1]
    manager.stop()



def test_live_transcode_capacity_uses_runtime_tuning_database(
    tmp_path: Path,
) -> None:
    FakeTimer.created = []
    configured = settings(
        tmp_path,
        live_transcode_max_derivatives=2,
    )
    database = Database(configured)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    try:
        with database.session() as session:
            RuntimeTuningSettingsService.update(
                session,
                settings=configured,
                changes={
                    "live_transcode_max_derivatives": 1,
                },
            )
            session.commit()

        manager = LiveTranscodeManager(
            configured,
            database=database,
            popen_factory=(
                lambda *_args, **_kwargs: FakeProcess()
            ),
            run_factory=(
                lambda *_args, **_kwargs: FakeCompleted()
            ),
            zlm_factory=FakeZlm,
            timer_factory=FakeTimer,
        )
        camera_id = uuid.uuid4()
        owner_user_id = uuid.uuid4()
        first_profile = uuid.uuid4()
        second_profile = uuid.uuid4()

        manager.acquire(
            camera_id=camera_id,
            owner_user_id=owner_user_id,
            profile_id=first_profile,
            source_url=(
                "rtsp://zlmediakit:554/zero-nvr/"
                f"profile-{first_profile.hex}"
            ),
            has_audio=False,
        )

        with pytest.raises(
            LiveTranscodeError
        ) as captured:
            manager.acquire(
                camera_id=camera_id,
                owner_user_id=owner_user_id,
                profile_id=second_profile,
                source_url=(
                    "rtsp://zlmediakit:554/zero-nvr/"
                    f"profile-{second_profile.hex}"
                ),
                has_audio=False,
            )

        assert (
            captured.value.code
            == "live_transcode_capacity"
        )
        manager.stop()
    finally:
        database.close()
