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
from app.modules.recordings.playback import (
    GapPlan,
    PlayablePlan,
    PlaybackResolverService,
)
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

        by_segment = client.post(
            (
                f"/api/v1/recordings/"
                f"{segment_id}/playback/resolve"
            ),
            json={"offset_ms": 30_000},
        )
        assert by_segment.status_code == 200
        assert (
            by_segment.json()["status"]
            == "pending"
        )
        assert (
            by_segment.json()["segment_id"]
            == str(segment_id)
        )
        assert fake_tasks.segment_ids == [
            segment_id
        ]

        by_time = client.post(
            f"/api/v1/cameras/{camera_id}/playback/resolve",
            json={
                "at": (
                    started_at + timedelta(seconds=30)
                ).isoformat()
            },
        )
        assert by_time.status_code == 200
        assert (
            by_time.json()["status"]
            == "pending"
        )
        assert fake_tasks.segment_ids == [
            segment_id
        ]



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

def test_playback_resolve_requires_camera_scope_and_returns_short_lived_signed_grant(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        secret_key="playback-grant-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'playback-grant.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=tmp_path / "recordings",
        session_cookie_secure=False,
        zlm_public_base_url="/zlm",
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)

    loaded: dict[str, object] = {}

    class FakeZlmAdapter:
        def __init__(self, _settings: Settings) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def load_mp4_file(
            self,
            *,
            app: str,
            stream: str,
            file_path: str,
            seek_ms: int,
            speed: float,
        ) -> bool:
            loaded.update(
                {
                    "app": app,
                    "stream": stream,
                    "file_path": file_path,
                    "seek_ms": seek_ms,
                    "speed": speed,
                }
            )
            return True

    monkeypatch.setattr(
        "app.modules.recordings.playback.ZlmAdapter",
        FakeZlmAdapter,
    )

    started_at = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    local_root = settings.recordings_dir
    local_root.mkdir(parents=True, exist_ok=True)
    media_path = local_root / "front-door.mp4"
    media_path.write_bytes(b"playback-media")

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
            camera = CameraService(
                settings
            ).create_manual_rtsp_camera(
                session,
                name="Front Door",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url=(
                    "rtsp://alice:camera-secret@camera.local/main"
                ),
                secondary_name=None,
                secondary_url=None,
            )
            profile_id = session.scalar(
                select(CameraStreamProfile.id).where(
                    CameraStreamProfile.camera_id
                    == camera.id,
                    CameraStreamProfile.adapter_profile_key
                    == "manual-primary",
                )
            )
            assert profile_id is not None
            target = StorageTarget(
                name="Local Recording",
                type="local",
                role="recording",
                enabled=True,
                config_json={
                    "path": str(local_root),
                    "default_recording": True,
                },
            )
            session.add(target)
            session.flush()
            segment = RecordingSegment(
                camera_id=camera.id,
                stream_profile_id=profile_id,
                started_at=started_at,
                ended_at=started_at + timedelta(minutes=5),
                duration_ms=300_000,
                timing_status="FINAL",
                timing_source="RECOVERY",
                recording_reasons_json=["continuous"],
                size_bytes=media_path.stat().st_size,
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
                    object_path=media_path.name,
                    state="AVAILABLE",
                    size_bytes=media_path.stat().st_size,
                )
            )
            session.commit()
            camera_id = camera.id
            segment_id = segment.id

        role = client.post(
            "/api/v1/roles",
            json={
                "name": "Scoped Playback",
                "permissions": ["recording.view"],
            },
        )
        assert role.status_code == 201

        user = client.post(
            "/api/v1/users",
            json={
                "username": "playback-viewer",
                "display_name": "Playback Viewer",
                "password": ADMIN_PASSWORD,
                "role_ids": [role.json()["id"]],
            },
        )
        assert user.status_code == 201
        user_id = user.json()["id"]

        client.cookies.clear()
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "playback-viewer",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200

        denied = client.post(
            f"/api/v1/cameras/{camera_id}/playback/resolve",
            json={
                "at": (
                    started_at + timedelta(seconds=15)
                ).isoformat()
            },
        )
        assert denied.status_code == 404
        assert (
            denied.json()["error"]["code"]
            == "camera_not_found"
        )

        denied_segment = client.post(
            (
                f"/api/v1/recordings/"
                f"{segment_id}/playback/resolve"
            ),
            json={"offset_ms": 15_000},
        )
        assert denied_segment.status_code == 404
        assert (
            denied_segment.json()["error"]["code"]
            == "recording_not_found"
        )

        client.cookies.clear()
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200
        selected = client.put(
            f"/api/v1/users/{user_id}/camera-scope",
            json={
                "mode": "selected",
                "camera_ids": [str(camera_id)],
            },
        )
        assert selected.status_code == 200

        client.cookies.clear()
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "playback-viewer",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200

        playable = client.post(
            f"/api/v1/cameras/{camera_id}/playback/resolve",
            json={
                "at": (
                    started_at + timedelta(seconds=15)
                ).isoformat()
            },
        )
        assert playable.status_code == 200
        body = playable.json()
        assert body["status"] == "playable"
        assert body["transport"] == "fmp4"
        assert body["offset_ms"] == 15_000
        assert body["url"].startswith(
            "/zlm/zero-nvr-vod/segment-"
        )
        assert ".live.mp4?" in body["url"]
        assert "zn_exp=" in body["url"]
        assert "zn_sig=" in body["url"]
        assert body["expires_at"]
        expiry = datetime.fromisoformat(
            body["expires_at"]
        )
        remaining = (
            expiry - datetime.now(UTC)
        ).total_seconds()
        assert 270 <= remaining <= 310

        assert loaded["app"] == "zero-nvr-vod"
        assert loaded["seek_ms"] == 15_000

        by_segment = client.post(
            (
                f"/api/v1/recordings/"
                f"{segment_id}/playback/resolve"
            ),
            json={"offset_ms": 30_000},
        )
        assert by_segment.status_code == 200
        by_segment_body = by_segment.json()
        assert (
            by_segment_body["status"]
            == "playable"
        )
        assert (
            by_segment_body["segment_id"]
            == str(segment_id)
        )
        assert (
            by_segment_body["offset_ms"]
            == 30_000
        )
        assert loaded["seek_ms"] == 30_000

        invalid_offset = client.post(
            (
                f"/api/v1/recordings/"
                f"{segment_id}/playback/resolve"
            ),
            json={"offset_ms": 300_000},
        )
        assert invalid_offset.status_code == 422
        assert (
            invalid_offset.json()["error"][
                "code"
            ]
            == "playback_offset_invalid"
        )

        serialized = (
            str(body)
            + str(by_segment_body)
            + str(loaded)
        )
        assert "rtsp://" not in serialized
        assert "camera-secret" not in serialized




def test_segment_resolver_does_not_play_purged_media_from_stale_cache(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path
    )
    try:
        (
            _camera_id,
            segment_id,
            _started_at,
        ) = seed_remote_segment(
            settings,
            database,
        )
        cache = PlaybackCacheService(settings)
        cache.root.mkdir(
            parents=True,
            exist_ok=True,
        )
        stale = (
            cache.root
            / f"{segment_id.hex}.mp4"
        )
        stale.write_bytes(b"x" * 32)

        with database.session() as session:
            location = session.scalar(
                select(
                    RecordingLocation
                ).where(
                    RecordingLocation
                    .recording_segment_id
                    == segment_id
                )
            )
            assert location is not None
            location.state = "DELETED"
            session.commit()

        with database.session() as session:
            plan = (
                PlaybackResolverService
                .plan_segment(
                    session,
                    segment_id=segment_id,
                    offset_ms=0,
                    settings=settings,
                )
            )

        assert isinstance(plan, GapPlan)
        assert plan.reason == "purged"
    finally:
        database.close()
