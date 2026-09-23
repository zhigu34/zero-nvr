from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.integrations.zlm import (
    ZlmContinuityTracker,
    ZlmObservedHealthStore,
)
from app.modules.cameras.runtime_observation import (
    ZlmRuntimeObservationService,
)
from app.modules.cameras.service import CameraService


class FakeZlm:
    def __init__(
        self,
        _settings: Settings,
    ) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(
        self,
        *_exc,
    ) -> None:
        return None

    def get_media_list(
        self,
        *,
        app: str,
        stream: str,
        schema: str,
    ):
        assert app == "zero-nvr"
        assert schema == "rtsp"
        assert stream.startswith(
            "profile-"
        )
        return [
            {
                "createStamp": 1_700_000_000,
                "isRecordingMP4": True,
            }
        ]


def test_rebuild_restores_online_media_recorder_and_continuity(
    tmp_path: Path,
) -> None:
    settings = Settings(
        secret_key=(
            "zlm-runtime-observation-test-"
            "secret-key-32-bytes-minimum"
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
    health = ZlmObservedHealthStore()
    continuity = ZlmContinuityTracker()
    observed_at = datetime(
        2026,
        9,
        23,
        4,
        0,
        tzinfo=UTC,
    )

    try:
        with database.session() as session:
            camera = CameraService(
                settings
            ).create_manual_rtsp_camera(
                session,
                name="Front Door",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url=(
                    "rtsp://camera.local/main"
                ),
                secondary_name=None,
                secondary_url=None,
            )
            profile_id = (
                camera.stream_profiles[0].id
            )
            session.commit()

        result = ZlmRuntimeObservationService(
            settings,
            database,
            health=health,
            continuity=continuity,
            adapter_factory=FakeZlm,
            now=lambda: observed_at,
        ).rebuild()

        assert result.profiles == 1
        assert result.online == 1
        assert result.recording == 1

        media = health.media(
            profile_id
        )
        recorder = health.recording(
            profile_id
        )
        assert media is not None
        assert media.online is True
        assert (
            media.observed_at
            == observed_at
        )
        assert recorder is not None
        assert recorder.active is True
        assert (
            recorder.observed_at
            == observed_at
        )
        assert (
            recorder.continuity_id
            == media.continuity_id
        )

        resolution = continuity.active_resolution(
            vhost="__defaultVhost__",
            app="zero-nvr",
            stream=(
                f"profile-{profile_id.hex}"
            ),
        )
        assert resolution is not None
        assert resolution.opened_at == (
            datetime.fromtimestamp(
                1_700_000_000,
                tz=UTC,
            )
        )
    finally:
        database.close()
