from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
import uuid

from app.core.config import Settings
from app.modules.recordings.dispatcher import RecordingTaskDispatcher


def test_recording_dispatcher_exposes_runtime_reconcile(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "ZERO_NVR_HUEY_DB_PATH",
        str(tmp_path / "huey.db"),
    )
    camera_id = uuid.uuid4()
    calls = []

    def fake_task(
        value: str,
        restart_streams: bool = False,
        force_reconfigure: bool = False,
    ) -> None:
        calls.append(
            (
                value,
                restart_streams,
                force_reconfigure,
            )
        )

    monkeypatch.setattr(
        "app.worker.tasks.reconcile_camera_runtime",
        fake_task,
    )

    RecordingTaskDispatcher.reconcile_runtime(camera_id)

    assert calls == [
        (str(camera_id), False, False)
    ]

    RecordingTaskDispatcher.reconcile_runtime(
        camera_id,
        restart_streams=True,
    )
    assert calls[-1] == (
        str(camera_id),
        True,
        False,
    )

    RecordingTaskDispatcher.reconcile_runtime(
        camera_id,
        force_reconfigure=True,
    )
    assert calls[-1] == (
        str(camera_id),
        False,
        True,
    )



def test_recording_dispatcher_exposes_catalog_reconcile(
    monkeypatch,
) -> None:
    calls: list[bool] = []

    monkeypatch.setattr(
        "app.worker.tasks.reconcile_recording_catalog",
        lambda full=False: calls.append(
            full
        ),
    )

    from app.modules.recordings.dispatcher import (
        RecordingTaskDispatcher,
    )

    RecordingTaskDispatcher.reconcile_catalog(
        full=True
    )
    assert calls == [True]



def test_recording_dispatcher_schedules_runtime_boundary(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "ZERO_NVR_HUEY_DB_PATH",
        str(tmp_path / "huey.db"),
    )
    camera_id = uuid.uuid4()
    eta = object()
    calls = []

    class FakeTask:
        def schedule(
            self,
            *,
            args,
            eta,
        ) -> None:
            calls.append((args, eta))

    monkeypatch.setattr(
        "app.worker.tasks.reconcile_camera_runtime",
        FakeTask(),
    )

    RecordingTaskDispatcher.schedule_runtime(
        camera_id,
        eta=eta,
        force_reconfigure=True,
    )

    assert calls == [
        (
            (
                str(camera_id),
                False,
                True,
            ),
            eta,
        )
    ]



def test_recording_dispatcher_schedules_manual_boundary(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "ZERO_NVR_HUEY_DB_PATH",
        str(tmp_path / "huey.db"),
    )
    camera_id = uuid.uuid4()
    eta = object()
    calls = []

    class FakeTask:
        def schedule(
            self,
            *,
            args,
            eta,
        ) -> None:
            calls.append((args, eta))

    monkeypatch.setattr(
        "app.worker.tasks.reconcile_manual_recording_boundary",
        FakeTask(),
    )

    RecordingTaskDispatcher.schedule_manual_boundary(
        camera_id,
        eta=eta,
    )

    assert calls == [
        ((str(camera_id),), eta)
    ]



def test_recording_dispatcher_uses_runtime_prebuffer_buffer_seconds(
    monkeypatch,
    tmp_path,
) -> None:
    settings = Settings(
        secret_key=(
            "recording-dispatcher-test-secret-key-"
            "32-bytes-minimum"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_buffer_seconds=35,
    )

    class FakeDatabase:
        @contextmanager
        def session(self):
            yield object()

    monkeypatch.setattr(
        "app.modules.recordings.dispatcher."
        "RuntimeTuningSettingsService.get",
        lambda _session, *, settings: SimpleNamespace(
            prebuffer_buffer_seconds=77
        ),
    )

    dispatcher = RecordingTaskDispatcher(
        settings,
        database=FakeDatabase(),  # type: ignore[arg-type]
    )

    assert (
        dispatcher._prebuffer_buffer_seconds()
        == 77
    )
