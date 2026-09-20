from __future__ import annotations

import uuid

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

    def fake_task(value: str) -> None:
        calls.append(value)

    monkeypatch.setattr(
        "app.worker.tasks.reconcile_camera_runtime",
        fake_task,
    )

    RecordingTaskDispatcher.reconcile_runtime(camera_id)

    assert calls == [str(camera_id)]



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
