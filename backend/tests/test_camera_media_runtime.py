from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.media_runtime import CameraMediaRuntimeService
from app.modules.cameras.service import CameraService


PRIMARY_URL = (
    "rtsp://alice:primary-password@10.0.0.21:8554/live/main"
    "?token=primary-token"
)
SECONDARY_URL = (
    "rtsp://alice:secondary-password@10.0.0.21:8554/live/sub"
    "?token=secondary-token"
)


def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key="media-runtime-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'media-runtime.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        zlm_api_secret="test-zlm-secret",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


class FakeZlm:
    online_streams: set[str] = set()
    instances = []

    def __init__(self, _settings) -> None:
        self.online_checks: list[str] = []
        self.add_calls: list[dict[str, object]] = []
        self.close_calls: list[dict[str, object]] = []
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def is_media_online(self, *, app: str, stream: str, schema: str = "rtsp"):
        assert app == "zero-nvr"
        assert schema == "rtsp"
        self.online_checks.append(stream)
        return stream in self.online_streams

    def add_stream_proxy(self, **kwargs):
        self.add_calls.append(kwargs)
        return f"__defaultVhost__/{kwargs['app']}/{kwargs['stream']}"

    def close_stream(self, **kwargs):
        self.close_calls.append(kwargs)
        return True


def test_desired_streams_deduplicate_bindings_and_hide_source_uri_in_repr(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)

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
                primary_url=PRIMARY_URL,
                secondary_name="Sub",
                secondary_url=SECONDARY_URL,
            )
            session.commit()
            camera_id = camera.id

        runtime = CameraMediaRuntimeService(
            settings,
            zlm_factory=FakeZlm,
        )

        with database.session() as session:
            camera = CameraService.get_camera(session, camera_id)
            desired = runtime.desired_streams(
                session,
                camera=camera,
            )
            references = runtime.stream_references(camera=camera)

        # Five business purposes map to only two physical source profiles.
        assert len(desired) == 2
        assert len(references) == 2
        assert {item.profile_id for item in desired} == {
            item.profile_id for item in references
        }
        assert all(item.app == "zero-nvr" for item in desired)
        assert all(
            item.stream == f"profile-{item.profile_id.hex}"
            for item in desired
        )

        rendered = repr(desired)
        assert "primary-password" not in rendered
        assert "secondary-password" not in rendered
        assert "primary-token" not in rendered
        assert "secondary-token" not in rendered
        assert "rtsp://" not in rendered
    finally:
        database.close()


def test_ensure_and_stop_streams_are_idempotent_against_zlm_state(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)

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
                primary_url=PRIMARY_URL,
                secondary_name="Sub",
                secondary_url=SECONDARY_URL,
            )
            session.commit()
            camera_id = camera.id

        FakeZlm.instances = []
        runtime = CameraMediaRuntimeService(
            settings,
            zlm_factory=FakeZlm,
        )

        with database.session() as session:
            camera = CameraService.get_camera(session, camera_id)
            desired = runtime.desired_streams(
                session,
                camera=camera,
            )
            session.commit()

        assert len(desired) == 2
        already_online = desired[0]
        to_add = desired[1]
        FakeZlm.online_streams = {already_online.stream}

        references = runtime.ensure_streams(desired)
        ensure_zlm = FakeZlm.instances[-1]

        assert len(references) == 2
        assert set(ensure_zlm.online_checks) == {
            already_online.stream,
            to_add.stream,
        }
        assert len(ensure_zlm.add_calls) == 1
        add_call = ensure_zlm.add_calls[0]
        assert add_call["stream"] == to_add.stream
        assert add_call["source_url"] == to_add.source_uri
        assert add_call["enable_mp4"] is False
        assert add_call["enable_hls"] is True
        assert add_call["retry_count"] == -1

        # Once both are online, stop should close both by deterministic ZLM
        # app/stream identity. No proxy-key runtime table is required.
        FakeZlm.online_streams = {
            item.stream for item in desired
        }
        runtime.stop_streams(references)
        stop_zlm = FakeZlm.instances[-1]

        assert {
            item["stream"]
            for item in stop_zlm.close_calls
        } == {
            item.stream for item in desired
        }
        assert all(
            item["force"] is True
            for item in stop_zlm.close_calls
        )
    finally:
        database.close()


def test_disabled_camera_has_no_desired_streams_but_keeps_stop_references(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)

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
                primary_url=PRIMARY_URL,
                secondary_name="Sub",
                secondary_url=SECONDARY_URL,
            )
            camera.enabled = False
            session.commit()
            camera_id = camera.id

        runtime = CameraMediaRuntimeService(
            settings,
            zlm_factory=FakeZlm,
        )

        with database.session() as session:
            camera = CameraService.get_camera(session, camera_id)
            assert runtime.desired_streams(
                session,
                camera=camera,
            ) == []
            assert len(
                runtime.stream_references(camera=camera)
            ) == 2
    finally:
        database.close()
