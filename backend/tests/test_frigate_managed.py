from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
)
from app.modules.cameras.service import CameraService
from app.modules.system.frigate import (
    FrigateCredentials,
    FrigateProviderSettingsService,
)
from app.modules.system.frigate_managed import (
    ManagedFrigateConfigService,
)


def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key="managed-frigate-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'managed-frigate.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        zlm_rtsp_base_url="rtsp://zlmediakit:554",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def test_managed_frigate_uses_only_zlm_ai_detect_stream_and_never_records(
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
                primary_url=(
                    "rtsp://admin:camera-secret@camera.local/main"
                ),
                secondary_name="Sub",
                secondary_url=(
                    "rtsp://admin:camera-secret@camera.local/sub"
                ),
            )
            session.flush()

            secondary = next(
                profile
                for profile in camera.stream_profiles
                if profile.adapter_profile_key
                == "manual-secondary"
            )
            secondary.codec = "h264"
            secondary.width = 640
            secondary.height = 360
            secondary.fps = 10

            provider = FrigateProviderSettingsService(
                settings
            ).put(
                session,
                enabled=True,
                mode="managed",
                base_url="http://frigate:5000",
                camera_map={"front_door": camera.id},
                mqtt_enabled=True,
                mqtt_host="mosquitto",
                mqtt_port=1883,
                mqtt_topic_prefix="frigate",
                mqtt_tls=False,
                credentials=FrigateCredentials(
                    mqtt_username="frigate-user",
                    mqtt_password="mqtt-super-secret",
                ),
                replace_credentials=True,
            )
            session.flush()

            plan = ManagedFrigateConfigService(
                settings
            ).build(
                session,
                provider=provider,
            )
            session.commit()

        camera_cfg = plan.config["cameras"]["front_door"]
        ffmpeg_input = camera_cfg["ffmpeg"]["inputs"][0]

        assert ffmpeg_input["roles"] == ["detect"]
        assert ffmpeg_input["path"] == (
            "rtsp://zlmediakit:554/zero-nvr/"
            f"profile-{secondary.id.hex}"
        )
        assert "camera.local" not in ffmpeg_input["path"]
        assert "camera-secret" not in ffmpeg_input["path"]

        assert camera_cfg["record"] == {"enabled": False}
        assert plan.config["record"] == {"enabled": False}
        assert camera_cfg["snapshots"] == {"enabled": True}
        assert camera_cfg["detect"] == {
            "enabled": True,
            "fps": 5,
            "width": 640,
            "height": 360,
        }

        assert plan.config["mqtt"]["host"] == (
            "{FRIGATE_MQTT_HOST}"
        )
        assert plan.config["mqtt"]["user"] == (
            "{FRIGATE_MQTT_USER}"
        )
        assert plan.config["mqtt"]["password"] == (
            "{FRIGATE_MQTT_PASSWORD}"
        )
        assert plan.environment == {
            "FRIGATE_MQTT_HOST": "mosquitto",
            "FRIGATE_MQTT_USER": "frigate-user",
            "FRIGATE_MQTT_PASSWORD": "mqtt-super-secret",
        }

        assert "mqtt-super-secret" not in plan.yaml_text
        assert "camera-secret" not in plan.yaml_text
        assert "frigate-user" not in plan.yaml_text

        assert len(plan.desired_streams) == 1
        desired = plan.desired_streams[0]
        assert desired.profile_id == secondary.id
        assert "camera-secret" in desired.source_uri
        assert "camera-secret" not in repr(desired)
    finally:
        database.close()


def test_disabled_camera_stays_in_generated_config_but_is_not_pulled(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        with database.session() as session:
            camera = CameraService(
                settings
            ).create_manual_rtsp_camera(
                session,
                name="Back Door",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url="rtsp://camera.local/main",
                secondary_name=None,
                secondary_url=None,
            )
            camera.enabled = False
            provider = FrigateProviderSettingsService(
                settings
            ).put(
                session,
                enabled=True,
                mode="managed",
                base_url="http://frigate:5000",
                camera_map={"back_door": camera.id},
                mqtt_enabled=False,
                mqtt_host=None,
                mqtt_port=1883,
                mqtt_topic_prefix="frigate",
                mqtt_tls=False,
            )
            session.flush()

            plan = ManagedFrigateConfigService(
                settings
            ).build(
                session,
                provider=provider,
            )
            session.commit()

        assert (
            plan.config["cameras"]["back_door"]["enabled"]
            is False
        )
        assert (
            plan.config["cameras"]["back_door"]["detect"]["enabled"]
            is False
        )
        assert plan.desired_streams == ()
    finally:
        database.close()


def test_managed_config_requires_ai_detect_binding(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        with database.session() as session:
            camera = CameraService(
                settings
            ).create_manual_rtsp_camera(
                session,
                name="Garage",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url="rtsp://camera.local/main",
                secondary_name=None,
                secondary_url=None,
            )
            session.query(CameraStreamBinding).filter(
                CameraStreamBinding.camera_id == camera.id,
                CameraStreamBinding.purpose == "AI_DETECT",
            ).delete()
            provider = FrigateProviderSettingsService(
                settings
            ).put(
                session,
                enabled=True,
                mode="managed",
                base_url="http://frigate:5000",
                camera_map={"garage": camera.id},
                mqtt_enabled=False,
                mqtt_host=None,
                mqtt_port=1883,
                mqtt_topic_prefix="frigate",
                mqtt_tls=False,
            )
            session.flush()

            try:
                ManagedFrigateConfigService(settings).build(
                    session,
                    provider=provider,
                )
            except Exception as exc:
                assert getattr(exc, "code", None) == (
                    "frigate_ai_stream_binding_missing"
                )
            else:
                raise AssertionError(
                    "expected missing AI_DETECT binding error"
                )
    finally:
        database.close()
