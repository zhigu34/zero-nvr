from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.runtime_reconciler import (
    RuntimeReconciler,
)
from app.modules.cameras.service import CameraService


def test_runtime_reconciler_queues_all_persisted_cameras(
    tmp_path: Path,
) -> None:
    settings = Settings(
        secret_key=(
            "runtime-reconciler-test-secret-key-"
            "32-bytes-minimum"
        ),
        database_url=(
            f"sqlite:///{tmp_path / 'runtime.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(
        database.engine
    )

    try:
        with database.session() as session:
            first = CameraService(
                settings
            ).create_manual_rtsp_camera(
                session,
                name="First",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url=(
                    "rtsp://camera.local/first"
                ),
                secondary_name=None,
                secondary_url=None,
            )
            second = CameraService(
                settings
            ).create_manual_rtsp_camera(
                session,
                name="Second",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url=(
                    "rtsp://camera.local/second"
                ),
                secondary_name=None,
                secondary_url=None,
            )
            second.enabled = False
            second.retired_at = first.created_at
            session.commit()
            expected = {
                first.id,
                second.id,
            }

        queued = []
        prebuffer = []
        catalog = []
        reconciler = RuntimeReconciler(
            database,
            reconcile_camera=queued.append,
            reconcile_prebuffer=(
                prebuffer.append
            ),
            reconcile_catalog=lambda: (
                catalog.append(True)
            ),
        )

        assert reconciler.enqueue_all() == 2
        assert set(queued) == expected
        assert set(prebuffer) == expected
        assert catalog == [True]
    finally:
        database.close()


def test_runtime_reconciler_stays_thin() -> None:
    source = Path(
        __file__
    ).resolve().parents[1] / (
        "app/modules/cameras/"
        "runtime_reconciler.py"
    )
    text = source.read_text(
        encoding="utf-8"
    )

    assert "ZlmAdapter" not in text
    assert "OnvifAdapter" not in text
    assert "RecordingRuntimeService" not in text
