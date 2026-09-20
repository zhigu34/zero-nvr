from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.integrations.rclone import RcloneIntegrationError
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingSegment
from app.modules.storage.archive import (
    ArchiveLifecycleError,
    ArchiveLifecycleService,
)
from app.modules.storage.dispatcher import StorageTaskDispatcher
from app.modules.storage.models import RecordingLocation
from app.modules.storage.service import StorageTargetService


RCLONE_CONFIG = """[archive]
type = webdav
url = https://example.invalid/dav
user = archive
pass = super-secret-rclone-password
"""


def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key="archive-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'archive.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=tmp_path / "recordings",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed(
    settings: Settings,
    database: Database,
    *,
    create_source: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, Path]:
    local_root = settings.recordings_dir
    local_root.mkdir(parents=True, exist_ok=True)

    with database.session() as session:
        camera = CameraService(
            settings
        ).create_manual_rtsp_camera(
            session,
            name="Front Door",
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url="rtsp://camera.local/main",
            secondary_name=None,
            secondary_url=None,
        )

        storage = StorageTargetService(settings)
        local = storage.create(
            session,
            target_type="local",
            role="recording",
            name="Local Recording",
            enabled=True,
            config={
                "path": str(local_root),
                "default_recording": True,
            },
            rclone_config=None,
        )
        remote = storage.create(
            session,
            target_type="rclone",
            role="archive",
            name="Cloud Archive",
            enabled=True,
            config={
                "remote": "archive",
                "base_path": "zero-nvr/archive",
            },
            rclone_config=RCLONE_CONFIG,
        )

        profile_id = session.scalar(
            select(CameraStreamProfile.id).where(
                CameraStreamProfile.camera_id == camera.id,
                CameraStreamProfile.adapter_profile_key
                == "manual-primary",
            )
        )
        assert profile_id is not None

        started = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
        segment = RecordingSegment(
            camera_id=camera.id,
            stream_profile_id=profile_id,
            started_at=started,
            ended_at=started + timedelta(seconds=10),
            duration_ms=10_000,
            timing_status="FINAL",
            timing_source="RECOVERY",
            recording_reasons_json=["continuous"],
            size_bytes=4096,
            codec="h264",
            container="fmp4",
            source_media_server_id="default",
            source_app="zero-nvr",
            source_stream=f"profile-{profile_id.hex}",
            integrity_status="OK",
            completion_reason="NORMAL",
        )
        session.add(segment)
        session.flush()

        object_path = (
            f"record/zero-nvr/profile-{profile_id.hex}/"
            "2026-09-20/segment-001.mp4"
        )
        session.add(
            RecordingLocation(
                recording_segment_id=segment.id,
                storage_target_id=local.id,
                object_path=object_path,
                state="AVAILABLE",
                size_bytes=4096,
            )
        )
        session.commit()

        segment_id = segment.id
        local_id = local.id
        remote_id = remote.id

    source = local_root / object_path
    if create_source:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"x" * 4096)

    return segment_id, local_id, remote_id, source


class SuccessfulAdapter:
    calls: list[dict[str, object]] = []
    config_texts: list[str] = []

    def __init__(
        self,
        *,
        config_text: str,
        binary: str,
        timeout_seconds: float,
    ) -> None:
        self.config_texts.append(config_text)

    def copy_to_remote(
        self,
        *,
        source: Path,
        destination: str,
        expected_size: int,
    ):
        self.calls.append(
            {
                "source": source,
                "destination": destination,
                "expected_size": expected_size,
            }
        )
        assert source.stat().st_size == expected_size
        return SimpleNamespace(
            path=destination,
            size_bytes=expected_size,
        )


class FailingAdapter:
    def __init__(self, **_kwargs) -> None:
        pass

    def copy_to_remote(self, **_kwargs):
        raise RcloneIntegrationError(
            "rclone_operation_failed",
            "rclone operation failed.",
        )


def test_archive_copy_verify_marks_remote_available_and_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        segment_id, local_id, remote_id, source = seed(
            settings,
            database,
        )

        SuccessfulAdapter.calls = []
        SuccessfulAdapter.config_texts = []
        service = ArchiveLifecycleService(
            settings,
            adapter_factory=SuccessfulAdapter,
        )

        first = service.execute(
            database,
            segment_id=segment_id,
            target_id=remote_id,
        )
        assert first.transferred is True
        assert first.already_available is False
        assert source.is_file()
        assert len(SuccessfulAdapter.calls) == 1

        call = SuccessfulAdapter.calls[0]
        assert call["source"] == source.resolve()
        assert call["expected_size"] == 4096
        assert call["destination"].startswith(
            "archive:zero-nvr/archive/"
        )
        assert (
            "super-secret-rclone-password"
            not in str(call["destination"])
        )
        assert SuccessfulAdapter.config_texts == [
            RCLONE_CONFIG
        ]

        with database.session() as session:
            remote = session.get(
                RecordingLocation,
                first.location_id,
            )
            assert remote is not None
            assert remote.storage_target_id == remote_id
            assert remote.state == "AVAILABLE"
            assert remote.verified_at is not None
            assert remote.last_error is None
            assert remote.size_bytes == 4096

            local = session.scalar(
                select(RecordingLocation).where(
                    RecordingLocation.storage_target_id
                    == local_id,
                    RecordingLocation.recording_segment_id
                    == segment_id,
                )
            )
            assert local is not None
            assert local.state == "AVAILABLE"

        retry = service.execute(
            database,
            segment_id=segment_id,
            target_id=remote_id,
        )
        assert retry.location_id == first.location_id
        assert retry.transferred is False
        assert retry.already_available is True
        assert len(SuccessfulAdapter.calls) == 1
    finally:
        database.close()


def test_archive_failure_marks_only_remote_failed_and_keeps_local(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        segment_id, local_id, remote_id, source = seed(
            settings,
            database,
        )

        service = ArchiveLifecycleService(
            settings,
            adapter_factory=FailingAdapter,
        )
        with pytest.raises(ArchiveLifecycleError) as captured:
            service.execute(
                database,
                segment_id=segment_id,
                target_id=remote_id,
            )

        assert captured.value.code == "rclone_operation_failed"
        assert source.is_file()

        with database.session() as session:
            remote = session.scalar(
                select(RecordingLocation).where(
                    RecordingLocation.storage_target_id
                    == remote_id,
                    RecordingLocation.recording_segment_id
                    == segment_id,
                )
            )
            assert remote is not None
            assert remote.state == "FAILED"
            assert remote.last_error == "rclone_operation_failed"
            assert remote.verified_at is None

            local = session.scalar(
                select(RecordingLocation).where(
                    RecordingLocation.storage_target_id
                    == local_id,
                    RecordingLocation.recording_segment_id
                    == segment_id,
                )
            )
            assert local is not None
            assert local.state == "AVAILABLE"
    finally:
        database.close()


def test_missing_source_marks_local_missing_and_remote_failed(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        segment_id, local_id, remote_id, source = seed(
            settings,
            database,
            create_source=False,
        )
        assert not source.exists()

        service = ArchiveLifecycleService(
            settings,
            adapter_factory=SuccessfulAdapter,
        )
        with pytest.raises(ArchiveLifecycleError) as captured:
            service.execute(
                database,
                segment_id=segment_id,
                target_id=remote_id,
            )
        assert captured.value.code == "archive_source_missing"

        with database.session() as session:
            local = session.scalar(
                select(RecordingLocation).where(
                    RecordingLocation.storage_target_id
                    == local_id,
                    RecordingLocation.recording_segment_id
                    == segment_id,
                )
            )
            remote = session.scalar(
                select(RecordingLocation).where(
                    RecordingLocation.storage_target_id
                    == remote_id,
                    RecordingLocation.recording_segment_id
                    == segment_id,
                )
            )
            assert local is not None
            assert local.state == "MISSING"
            assert remote is not None
            assert remote.state == "FAILED"
            assert remote.last_error == "archive_source_missing"
    finally:
        database.close()


def test_storage_dispatcher_queues_only_stable_ids(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_task(segment_id: str, target_id: str) -> None:
        calls.append((segment_id, target_id))

    import app.worker.tasks as tasks

    monkeypatch.setattr(
        tasks,
        "archive_recording_segment",
        fake_task,
    )

    segment_id = uuid.uuid4()
    target_id = uuid.uuid4()
    StorageTaskDispatcher.archive_segment(
        segment_id=segment_id,
        target_id=target_id,
    )

    assert calls == [
        (str(segment_id), str(target_id))
    ]
    serialized = repr(calls)
    assert "rclone" not in serialized.lower()
    assert "secret" not in serialized.lower()
