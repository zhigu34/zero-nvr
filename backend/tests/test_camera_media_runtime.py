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
        self.wait_calls: list[dict[str, object]] = []
        self.close_calls: list[dict[str, object]] = []
        self.delete_calls: list[str] = []
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

    def wait_media_online(
        self,
        *,
        app: str,
        stream: str,
        timeout_seconds: float,
        schema: str = "rtsp",
    ):
        self.wait_calls.append(
            {
                "app": app,
                "stream": stream,
                "timeout_seconds": timeout_seconds,
                "schema": schema,
            }
        )
        return True

    def close_stream(self, **kwargs):
        self.close_calls.append(kwargs)
        return True

    def delete_stream_proxy(
        self,
        key: str,
    ):
        self.delete_calls.append(key)


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
        by_source = {
            item.source_uri: item
            for item in desired
        }
        assert by_source[PRIMARY_URL].auto_close is True
        assert by_source[SECONDARY_URL].auto_close is True

        rendered = repr(desired)
        assert "primary-password" not in rendered
        assert "secondary-password" not in rendered
        assert "primary-token" not in rendered
        assert "secondary-token" not in rendered
        assert "rtsp://" not in rendered
    finally:
        database.close()


def test_desired_stream_resolves_only_selected_profile(
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
        resolved: list[object] = []

        with database.session() as session:
            camera = CameraService.get_camera(
                session,
                camera_id,
            )
            selected = next(
                profile
                for profile in camera.stream_profiles
                if profile.adapter_profile_key
                == "manual-secondary"
            )

            def resolve_only_selected(
                _session,
                profile,
            ) -> str:
                resolved.append(profile.id)
                return SECONDARY_URL

            runtime._camera_service.resolve_stream_uri = (
                resolve_only_selected
            )
            desired = runtime.desired_stream(
                session,
                camera=camera,
                profile=selected,
            )

        assert resolved == [selected.id]
        assert desired.profile_id == selected.id
        assert desired.source_uri == SECONDARY_URL
        assert desired.stream == (
            f"profile-{selected.id.hex}"
        )
        assert desired.auto_close is True
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

        references = runtime.ensure_streams(
            desired,
            wait_online_seconds=3.0,
        )
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
        assert add_call["auto_close"] is True
        assert add_call["mp4_as_player"] is True
        assert ensure_zlm.wait_calls == [
            {
                "app": "zero-nvr",
                "stream": to_add.stream,
                "timeout_seconds": 3.0,
                "schema": "rtsp",
            }
        ]

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



def test_replace_streams_deletes_proxy_keys_before_readding(
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
            camera = CameraService.get_camera(
                session,
                camera_id,
            )
            desired = runtime.desired_streams(
                session,
                camera=camera,
            )
            session.commit()

        references = runtime.replace_streams(desired)
        zlm = FakeZlm.instances[-1]
        assert zlm.delete_calls == [
            item.reference.proxy_key
            for item in desired
        ]
        assert [
            item["stream"]
            for item in zlm.add_calls
        ] == [
            item.stream
            for item in desired
        ]
        assert all(
            item["retry_count"] == -1
            for item in zlm.add_calls
        )
        assert {
            item.proxy_key
            for item in references
        } == {
            "__defaultVhost__/zero-nvr/"
            + item.stream
            for item in desired
        }
    finally:
        database.close()


def test_replace_online_streams_only_restarts_active_profiles(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path
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
            camera = CameraService.get_camera(
                session,
                camera_id,
            )
            desired = runtime.desired_streams(
                session,
                camera=camera,
            )
            session.commit()

        assert len(desired) == 2
        active = desired[0]
        inactive = desired[1]
        FakeZlm.online_streams = {
            active.stream
        }

        replaced = (
            runtime.replace_online_streams(
                [active, inactive]
            )
        )
        zlm = FakeZlm.instances[-1]

        assert set(
            zlm.online_checks
        ) == {
            active.stream,
            inactive.stream,
        }
        assert zlm.delete_calls == [
            active.reference.proxy_key
        ]
        assert [
            item["stream"]
            for item in zlm.add_calls
        ] == [
            active.stream
        ]
        assert [
            item.profile_id
            for item in replaced
        ] == [
            active.profile_id
        ]
    finally:
        database.close()


def test_media_runtime_does_not_implement_rtsp_reconnect_backoff() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app/modules/cameras/media_runtime.py"
    ).read_text(encoding="utf-8").lower()

    for forbidden in (
        "time.sleep",
        "asyncio.sleep",
        "backoff",
        "reconnect_delay",
        "retry_delay",
    ):
        assert forbidden not in source, (
            "CameraMediaRuntimeService must delegate camera RTSP "
            f"reconnect/backoff to ZLMediaKit; found {forbidden!r}"
        )

    assert "retry_count=-1" in source


def test_persistent_camera_proxy_lifecycle_stays_in_media_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    media_runtime = (
        root / "app/modules/cameras/media_runtime.py"
    ).read_text(encoding="utf-8")

    assert "add_stream_proxy(" in media_runtime
    assert "delete_stream_proxy(" in media_runtime
    assert "close_stream(" in media_runtime

    for relative in (
        "app/modules/cameras/api.py",
        "app/modules/cameras/service.py",
        "app/modules/cameras/onvif_onboarding.py",
        "app/modules/cameras/discovery_service.py",
    ):
        source = (root / relative).read_text(
            encoding="utf-8"
        )
        assert ".add_stream_proxy(" not in source, (
            f"{relative} must delegate persistent camera proxy "
            "creation to CameraMediaRuntimeService"
        )
        assert ".delete_stream_proxy(" not in source, (
            f"{relative} must delegate persistent camera proxy "
            "removal to CameraMediaRuntimeService"
        )
