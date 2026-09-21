from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.integrations.rclone import RcloneStat
from app.main import create_app
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingSegment
from app.modules.recordings.playback import PlayablePlan, PlaybackResolverService
from app.modules.recordings.playback_cache import PlaybackCacheService
from app.modules.storage.models import RecordingLocation, StorageTarget
from app.modules.storage.service import ResolvedRcloneTarget
from app.modules.system.settings import (
    RuntimeTuningSettingsService,
)


ADMIN_PASSWORD = "correct-horse-battery-staple"


class FakeTargetService:
    def __init__(self, _settings: Settings) -> None:
        pass

    def resolve_rclone(self, _session, *, target: StorageTarget):
        return ResolvedRcloneTarget(
            target_id=target.id,
            remote="archive",
            base_path="zero-nvr",
            config_text="[archive]\ntype = local\n",
        )


class FakeRclone:
    calls: list[tuple[str, Path, int | None]] = []

    def __init__(self, **_kwargs) -> None:
        pass

    def copy_to_local(
        self,
        *,
        source: str,
        destination: Path,
        expected_size: int | None = None,
    ) -> RcloneStat:
        assert expected_size is not None
        self.calls.append((source, destination, expected_size))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"x" * expected_size)
        return RcloneStat(
            path=str(destination),
            size_bytes=expected_size,
        )


def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key="playback-cache-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'playback-cache.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        playback_cache_max_bytes=64 * 1024 * 1024,
        session_cookie_secure=False,
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed_remote_segment(
    settings: Settings,
    database: Database,
) -> tuple[object, object, datetime]:
    with database.session() as session:
        camera = CameraService(settings).create_manual_rtsp_camera(
            session,
            name="Front Door",
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url="rtsp://camera.local/main",
            secondary_name=None,
            secondary_url=None,
        )
        profile_id = session.scalar(
            select(CameraStreamProfile.id).where(
                CameraStreamProfile.camera_id == camera.id,
                CameraStreamProfile.adapter_profile_key
                == "manual-primary",
            )
        )
        assert profile_id is not None

        target = StorageTarget(
            name="Archive",
            type="rclone",
            role="archive",
            enabled=True,
            config_json={
                "remote": "archive",
                "base_path": "zero-nvr",
            },
        )
        session.add(target)
        session.flush()

        started_at = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
        segment = RecordingSegment(
            camera_id=camera.id,
            stream_profile_id=profile_id,
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=5),
            duration_ms=300_000,
            timing_status="FINAL",
            timing_source="RECOVERY",
            recording_reasons_json=["continuous"],
            size_bytes=32,
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
        session.add(
            RecordingLocation(
                recording_segment_id=segment.id,
                storage_target_id=target.id,
                object_path="2026/09/20/front-door.mp4",
                state="AVAILABLE",
                size_bytes=32,
            )
        )
        session.commit()
        return camera.id, segment.id, started_at


def test_remote_restore_becomes_playable_from_ephemeral_cache(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id, segment_id, started_at = seed_remote_segment(
            settings,
            database,
        )
        FakeRclone.calls = []
        cache = PlaybackCacheService(
            settings,
            adapter_factory=FakeRclone,
            target_service_factory=FakeTargetService,
        )

        restored = cache.execute(
            database,
            segment_id=segment_id,
        )
        assert restored.restored is True
        assert restored.path.is_file()
        assert restored.path.stat().st_size == 32
        assert FakeRclone.calls[0][0].endswith(
            "2026/09/20/front-door.mp4"
        )

        second = cache.execute(
            database,
            segment_id=segment_id,
        )
        assert second.already_cached is True
        assert len(FakeRclone.calls) == 1

        with database.session() as session:
            plan = PlaybackResolverService.plan(
                session,
                camera_id=camera_id,
                at=started_at + timedelta(seconds=15),
                settings=settings,
            )
        assert isinstance(plan, PlayablePlan)
        assert plan.file_path == restored.path
        assert plan.offset_ms == 15_000
    finally:
        database.close()


def test_pending_playback_queues_restore(tmp_path: Path) -> None:
    settings = Settings(
        secret_key="playback-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'playback-api.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)

    class FakeStorageTasks:
        def __init__(self) -> None:
            self.segment_ids = []

        def restore_playback_segment(self, *, segment_id) -> None:
            self.segment_ids.append(segment_id)

    fake_tasks = FakeStorageTasks()
    app.state.storage_tasks = fake_tasks

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 201
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200

        with app.state.database.session() as session:
            camera = CameraService(settings).create_manual_rtsp_camera(
                session,
                name="Front Door",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url="rtsp://camera.local/main",
                secondary_name=None,
                secondary_url=None,
            )
            profile_id = session.scalar(
                select(CameraStreamProfile.id).where(
                    CameraStreamProfile.camera_id == camera.id,
                    CameraStreamProfile.adapter_profile_key
                    == "manual-primary",
                )
            )
            assert profile_id is not None
            target = StorageTarget(
                name="Archive",
                type="rclone",
                role="archive",
                enabled=True,
                config_json={"remote": "archive"},
            )
            session.add(target)
            session.flush()
            started_at = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
            segment = RecordingSegment(
                camera_id=camera.id,
                stream_profile_id=profile_id,
                started_at=started_at,
                ended_at=started_at + timedelta(minutes=5),
                duration_ms=300_000,
                timing_status="FINAL",
                timing_source="RECOVERY",
                recording_reasons_json=["continuous"],
                size_bytes=64,
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
            session.add(
                RecordingLocation(
                    recording_segment_id=segment.id,
                    storage_target_id=target.id,
                    object_path="remote-only.mp4",
                    state="AVAILABLE",
                    size_bytes=64,
                )
            )
            session.commit()
            camera_id = camera.id
            segment_id = segment.id

        response = client.post(
            f"/api/v1/cameras/{camera_id}/playback/resolve",
            json={
                "at": (
                    started_at + timedelta(seconds=30)
                ).isoformat()
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "pending"
        assert response.json()["segment_id"] == str(segment_id)
        assert fake_tasks.segment_ids == [segment_id]

        again = client.post(
            f"/api/v1/cameras/{camera_id}/playback/resolve",
            json={
                "at": (
                    started_at + timedelta(seconds=30)
                ).isoformat()
            },
        )
        assert again.status_code == 200
        assert again.json()["status"] == "pending"
        assert fake_tasks.segment_ids == [segment_id]



def test_playback_cache_uses_runtime_tuning_from_database(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        with database.session() as session:
            RuntimeTuningSettingsService.update(
                session,
                settings=settings,
                changes={
                    "playback_cache_ttl_seconds": 60,
                },
            )
            session.commit()

        _camera_id, segment_id, _started_at = (
            seed_remote_segment(
                settings,
                database,
            )
        )
        cache = PlaybackCacheService(
            settings,
            adapter_factory=FakeRclone,
            target_service_factory=FakeTargetService,
        )
        cache.root.mkdir(
            parents=True,
            exist_ok=True,
        )
        stale = cache.root / "stale.mp4"
        stale.write_bytes(b"stale")
        expired = time.time() - 120
        os.utime(
            stale,
            (expired, expired),
        )

        FakeRclone.calls = []
        result = cache.execute(
            database,
            segment_id=segment_id,
        )

        assert result.restored is True
        assert stale.exists() is False
        assert len(FakeRclone.calls) == 1
    finally:
        database.close()
