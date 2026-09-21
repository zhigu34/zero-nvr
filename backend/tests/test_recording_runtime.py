from __future__ import annotations

import uuid
from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingPolicy
from app.modules.storage.models import StorageTarget
from app.modules.recordings.runtime import (
    DesiredRecorder,
    RecorderModeTracker,
    RecordingRuntimeService,
)


class FakeZlm:
    online = True
    recording = False
    calls: list[tuple] = []

    def __init__(self, _settings) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def is_stream_online(self, *, app: str, stream: str) -> bool:
        self.calls.append(("online", app, stream))
        return self.online

    def is_recording(self, *, app: str, stream: str) -> bool:
        self.calls.append(("is", app, stream))
        return self.recording

    def start(
        self,
        *,
        app: str,
        stream: str,
        customized_path: str,
        max_second: int,
    ) -> bool:
        self.calls.append(
            ("start", app, stream, customized_path, max_second)
        )
        self.__class__.recording = True
        return True

    def stop(self, *, app: str, stream: str) -> bool:
        self.calls.append(("stop", app, stream))
        self.__class__.recording = False
        return True


def settings(tmp_path: Path) -> Settings:
    return Settings(
        secret_key="runtime-test-secret-key-32-bytes-minimum",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_fragment_seconds=5,
    )


def desired(
    *,
    mode: str,
    root: str | None,
    max_second: int,
) -> DesiredRecorder:
    return DesiredRecorder(
        camera_id=uuid.uuid4(),
        profile_id=uuid.uuid4(),
        app="zero-nvr",
        stream="profile-test",
        mode=mode,  # type: ignore[arg-type]
        target_root=root,
        max_second=max_second,
    )


def reset(*, online: bool = True, recording: bool = False) -> None:
    FakeZlm.online = online
    FakeZlm.recording = recording
    FakeZlm.calls = []


def test_persistent_starts_native_recorder(tmp_path: Path) -> None:
    reset()
    tracker = RecorderModeTracker()
    service = RecordingRuntimeService(
        settings(tmp_path),
        zlm_factory=FakeZlm,
        mode_tracker=tracker,
    )
    item = desired(
        mode="persistent",
        root="/recordings",
        max_second=300,
    )

    result = service.reconcile(item)

    assert result.desired_mode == "persistent"
    assert result.observed_recording is True
    assert result.changed is True
    assert (
        "start",
        "zero-nvr",
        "profile-test",
        "/recordings",
        300,
    ) in FakeZlm.calls
    assert tracker.get(
        app="zero-nvr",
        stream="profile-test",
    ) == "persistent"


def test_mode_switch_stops_then_starts_same_zlm_recorder(tmp_path: Path) -> None:
    reset(recording=True)
    tracker = RecorderModeTracker()
    tracker.set(
        app="zero-nvr",
        stream="profile-test",
        mode="persistent",
    )
    service = RecordingRuntimeService(
        settings(tmp_path),
        zlm_factory=FakeZlm,
        mode_tracker=tracker,
    )

    result = service.reconcile(
        desired(
            mode="prebuffer",
            root="/prebuffer",
            max_second=5,
        )
    )

    assert result.desired_mode == "prebuffer"
    assert result.changed is True
    stop_index = FakeZlm.calls.index(
        ("stop", "zero-nvr", "profile-test")
    )
    start_index = FakeZlm.calls.index(
        ("start", "zero-nvr", "profile-test", "/prebuffer", 5)
    )
    assert stop_index < start_index
    assert tracker.get(
        app="zero-nvr",
        stream="profile-test",
    ) == "prebuffer"


def test_unknown_running_mode_after_api_restart_is_not_interrupted(
    tmp_path: Path,
) -> None:
    reset(recording=True)
    service = RecordingRuntimeService(
        settings(tmp_path),
        zlm_factory=FakeZlm,
        mode_tracker=RecorderModeTracker(),
    )

    result = service.reconcile(
        desired(
            mode="persistent",
            root="/recordings",
            max_second=300,
        ),
        force_reconfigure=False,
    )

    assert result.changed is False
    assert result.assumed_existing_mode is True
    assert not any(call[0] == "stop" for call in FakeZlm.calls)
    assert not any(call[0] == "start" for call in FakeZlm.calls)


def test_explicit_policy_reconfigure_restarts_unknown_running_mode(
    tmp_path: Path,
) -> None:
    reset(recording=True)
    service = RecordingRuntimeService(
        settings(tmp_path),
        zlm_factory=FakeZlm,
        mode_tracker=RecorderModeTracker(),
    )

    result = service.reconcile(
        desired(
            mode="prebuffer",
            root="/prebuffer",
            max_second=5,
        ),
        force_reconfigure=True,
    )

    assert result.changed is True
    assert ("stop", "zero-nvr", "profile-test") in FakeZlm.calls
    assert (
        "start",
        "zero-nvr",
        "profile-test",
        "/prebuffer",
        5,
    ) in FakeZlm.calls


def test_offline_stream_is_already_off_without_camera_pull(
    tmp_path: Path,
) -> None:
    reset(online=False, recording=False)
    service = RecordingRuntimeService(
        settings(tmp_path),
        zlm_factory=FakeZlm,
    )

    result = service.reconcile(
        desired(mode="off", root=None, max_second=0)
    )

    assert result.desired_mode == "off"
    assert result.observed_recording is False
    assert FakeZlm.calls == [
        ("online", "zero-nvr", "profile-test")
    ]



def test_explicit_policy_target_overrides_system_default_for_zlm_path(
    tmp_path: Path,
) -> None:
    reset()
    cfg = Settings(
        secret_key=(
            "runtime-routing-test-secret-key-"
            "32-bytes-minimum"
        ),
        database_url=(
            f"sqlite:///{tmp_path / 'runtime-routing.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
    )
    database = Database(cfg)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)

    default_root = tmp_path / "default-recordings"
    explicit_root = tmp_path / "camera-recordings"
    default_root.mkdir(parents=True)
    explicit_root.mkdir(parents=True)

    try:
        with database.session() as session:
            camera = CameraService(
                cfg
            ).create_manual_rtsp_camera(
                session,
                name="Explicit Target Camera",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url=(
                    "rtsp://camera.local/explicit"
                ),
                secondary_name=None,
                secondary_url=None,
            )

            default_target = StorageTarget(
                name="System Default",
                type="local",
                role="recording",
                enabled=True,
                config_json={
                    "path": str(default_root),
                    "default_recording": True,
                },
            )
            explicit_target = StorageTarget(
                name="Camera Target",
                type="local",
                role="recording",
                enabled=True,
                config_json={
                    "path": str(explicit_root),
                    "default_recording": False,
                },
            )
            session.add_all(
                [default_target, explicit_target]
            )
            session.flush()

            session.add(
                RecordingPolicy(
                    camera_id=camera.id,
                    baseline_mode="continuous",
                    storage_target_id=explicit_target.id,
                    segment_target_seconds=300,
                    enabled=True,
                )
            )
            session.commit()
            camera_id = camera.id

        with database.session() as session:
            item = RecordingRuntimeService.desired(
                session,
                settings=cfg,
                camera_id=camera_id,
            )
            assert item is not None
            assert item.mode == "persistent"
            assert item.target_root == str(
                explicit_root.resolve()
            )

        service = RecordingRuntimeService(
            cfg,
            zlm_factory=FakeZlm,
            mode_tracker=RecorderModeTracker(),
        )
        result = service.reconcile(item)

        assert result.observed_recording is True
        assert any(
            call[0] == "start"
            and call[3] == str(
                explicit_root.resolve()
            )
            for call in FakeZlm.calls
        )
        assert not any(
            call[0] == "start"
            and call[3] == str(
                default_root.resolve()
            )
            for call in FakeZlm.calls
        )
    finally:
        database.close()
