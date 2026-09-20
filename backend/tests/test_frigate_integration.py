from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.integrations.frigate import (
    FrigateEventNormalizer,
    FrigateHttpAdapter,
    FrigateIntegrationError,
)
from app.modules.auth.models import SecretRecord
from app.modules.cameras.service import CameraService
from app.modules.events.frigate import FrigateEventIngestService
from app.modules.events.models import Event
from app.modules.system.frigate import (
    FrigateCredentials,
    FrigateProviderSettingsService,
)
from app.modules.system.models import SystemSetting


def make_database(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key=SecretStr(
            "frigate-test-secret-key-32-bytes-minimum"
        ),
        database_url=f"sqlite:///{tmp_path / 'frigate.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed_camera(
    settings: Settings,
    database: Database,
) -> uuid.UUID:
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
        session.commit()
        return camera.id


def mqtt_payload(
    *,
    event_id: str = "event-1",
    message_type: str = "new",
    end_time: float | None = None,
    false_positive: bool = False,
) -> dict[str, object]:
    return {
        "type": message_type,
        "before": {},
        "after": {
            "id": event_id,
            "camera": "front_door",
            "label": "person",
            "sub_label": ["Alice", 0.91],
            "top_score": 0.96,
            "false_positive": false_positive,
            "start_time": 1_700_000_000.0,
            "end_time": end_time,
            "current_zones": ["driveway"],
            "entered_zones": ["yard", "driveway"],
            "has_snapshot": True,
            "has_clip": False,
            "attributes": {"face": 0.88},
            "recognized_license_plate": None,
        },
    }


def test_mqtt_new_update_end_upserts_one_canonical_event(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id = seed_camera(settings, database)
        service = FrigateProviderSettingsService(settings)

        with database.session() as session:
            config = service.put(
                session,
                enabled=True,
                mode="external",
                base_url="http://frigate.local:5000",
                camera_map={
                    "front_door": camera_id,
                },
                mqtt_enabled=True,
                mqtt_host="mqtt.local",
                mqtt_port=1883,
                mqtt_topic_prefix="frigate",
                mqtt_tls=False,
            )
            session.commit()
            instance_id = config.instance_id

        with database.session() as session:
            config = service.get(session)
            assert config is not None

            created = FrigateEventIngestService.mqtt(
                session,
                config=config,
                payload=mqtt_payload(),
            )
            assert created.created is True
            assert created.event is not None
            event_id = created.event.id
            session.commit()

        with database.session() as session:
            config = service.get(session)
            assert config is not None
            updated_payload = mqtt_payload(
                message_type="update",
            )
            updated_payload["after"]["top_score"] = 0.99
            updated_payload["after"]["entered_zones"] = [
                "yard",
                "driveway",
                "porch",
            ]
            updated = FrigateEventIngestService.mqtt(
                session,
                config=config,
                payload=updated_payload,
            )
            assert updated.created is False
            assert updated.event is not None
            assert updated.event.id == event_id
            assert updated.event.confidence == 0.99
            session.commit()

        with database.session() as session:
            config = service.get(session)
            assert config is not None
            ended = FrigateEventIngestService.mqtt(
                session,
                config=config,
                payload=mqtt_payload(
                    message_type="end",
                    end_time=1_700_000_030.0,
                ),
            )
            assert ended.created is False
            assert ended.event is not None
            assert ended.event.id == event_id
            assert ended.event.ended_at == datetime.fromtimestamp(
                1_700_000_030.0,
                tz=UTC,
            )
            session.commit()

            rows = list(session.scalars(select(Event)))
            assert len(rows) == 1
            event = rows[0]
            assert event.source == "frigate"
            assert event.source_instance_id == instance_id
            assert event.source_event_id == "event-1"
            assert event.camera_id == camera_id
            assert event.category == "object"
            assert event.label == "person"
            assert event.zone == "yard"
            assert event.snapshot_ref == (
                f"frigate://{instance_id}/event/event-1/snapshot"
            )
            assert event.metadata_json["zones"] == [
                "driveway",
                "yard",
            ]
            assert event.metadata_json["sub_label"] == "Alice"
            assert event.metadata_json["attributes"] == {
                "face": 0.88
            }
            # Raw boxes/regions/full provider messages are deliberately not
            # mirrored into the product DB.
            assert "box" not in event.metadata_json
            assert "before" not in event.metadata_json
    finally:
        database.close()


def test_http_backfill_uses_same_provider_identity_as_mqtt(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id = seed_camera(settings, database)
        config_service = FrigateProviderSettingsService(settings)

        with database.session() as session:
            config = config_service.put(
                session,
                enabled=True,
                mode="external",
                base_url="http://frigate.local",
                camera_map={"front_door": camera_id},
                mqtt_enabled=False,
                mqtt_host=None,
                mqtt_port=1883,
                mqtt_topic_prefix="frigate",
                mqtt_tls=False,
            )
            session.commit()

        with database.session() as session:
            config = config_service.get(session)
            assert config is not None
            first = FrigateEventIngestService.mqtt(
                session,
                config=config,
                payload=mqtt_payload(),
            )
            assert first.event is not None
            event_id = first.event.id
            session.commit()

        with database.session() as session:
            config = config_service.get(session)
            assert config is not None
            backfill = FrigateEventIngestService.http(
                session,
                config=config,
                payload={
                    "id": "event-1",
                    "camera": "front_door",
                    "label": "person",
                    "sub_label": "Alice",
                    "top_score": 0.98,
                    "false_positive": False,
                    "start_time": 1_700_000_000.0,
                    "end_time": 1_700_000_040.0,
                    "zones": ["yard"],
                    "has_snapshot": True,
                    "has_clip": True,
                    "data": {
                        "recognized_license_plate": None,
                    },
                },
            )
            assert backfill.created is False
            assert backfill.event is not None
            assert backfill.event.id == event_id
            assert backfill.event.ended_at == datetime.fromtimestamp(
                1_700_000_040.0,
                tz=UTC,
            )
            session.commit()
            assert len(list(session.scalars(select(Event)))) == 1
    finally:
        database.close()


def test_false_positive_and_unmapped_camera_are_ignored() -> None:
    mapped = FrigateEventNormalizer.mqtt_event(
        instance_id="instance-a",
        camera_map={"front_door": uuid.uuid4()},
        payload=mqtt_payload(false_positive=True),
    )
    assert mapped.ignored is True
    assert mapped.ignore_reason == "false_positive"

    unmapped = FrigateEventNormalizer.mqtt_event(
        instance_id="instance-a",
        camera_map={},
        payload=mqtt_payload(),
    )
    assert unmapped.ignored is True
    assert unmapped.ignore_reason == "camera_unmapped"


def test_provider_settings_encrypt_credentials_and_keep_instance_stable(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id = seed_camera(settings, database)
        service = FrigateProviderSettingsService(settings)

        with database.session() as session:
            first = service.put(
                session,
                enabled=True,
                mode="external",
                base_url="https://frigate.example.test",
                camera_map={"front_door": camera_id},
                mqtt_enabled=True,
                mqtt_host="mqtt.example.test",
                mqtt_port=8883,
                mqtt_topic_prefix="frigate",
                mqtt_tls=True,
                credentials=FrigateCredentials(
                    http_bearer_token="http-secret-token",
                    mqtt_username="mqtt-user",
                    mqtt_password="mqtt-secret-password",
                ),
                replace_credentials=True,
            )
            session.commit()
            first_id = first.instance_id

        with database.session() as session:
            setting = session.get(
                SystemSetting,
                "ai.frigate",
            )
            assert setting is not None
            rendered = repr(setting.value_json)
            assert "http-secret-token" not in rendered
            assert "mqtt-secret-password" not in rendered
            assert "mqtt-user" not in rendered

            secrets = list(
                session.scalars(
                    select(SecretRecord).where(
                        SecretRecord.kind
                        == "frigate_credentials"
                    )
                )
            )
            assert len(secrets) == 1
            assert b"http-secret-token" not in secrets[0].encrypted_payload
            assert b"mqtt-secret-password" not in secrets[0].encrypted_payload

            resolved = service.get(session)
            assert resolved is not None
            assert resolved.instance_id == first_id
            assert "http-secret-token" not in repr(resolved)
            assert "mqtt-secret-password" not in repr(resolved)
            assert (
                resolved.credentials.http_bearer_token
                == "http-secret-token"
            )
            assert (
                resolved.credentials.mqtt_password
                == "mqtt-secret-password"
            )

            updated = service.put(
                session,
                enabled=True,
                mode="external",
                base_url="https://frigate-new.example.test",
                camera_map={"front_door": camera_id},
                mqtt_enabled=False,
                mqtt_host=None,
                mqtt_port=1883,
                mqtt_topic_prefix="frigate",
                mqtt_tls=False,
                replace_credentials=False,
            )
            session.commit()
            assert updated.instance_id == first_id
            assert (
                updated.credentials.http_bearer_token
                == "http-secret-token"
            )
    finally:
        database.close()


def test_http_adapter_sanitizes_errors_and_fetches_events() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/version":
            return httpx.Response(
                200,
                json="0.16.0",
            )
        if request.url.path == "/api/events":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "event-1",
                        "camera": "front_door",
                    }
                ],
            )
        raise AssertionError(request.url.path)

    with FrigateHttpAdapter(
        base_url="http://frigate.local",
        bearer_token="super-secret-token",
        transport=httpx.MockTransport(handler),
    ) as adapter:
        version = adapter.version()
        assert version.version == "0.16.0"
        events = adapter.events(
            after=100.0,
            before=200.0,
            cameras=["front_door"],
            limit=50,
        )
        assert events[0]["id"] == "event-1"
        assert (
            adapter.snapshot_url("event-1")
            == "http://frigate.local/api/events/event-1/snapshot.jpg"
        )

    assert requests
    for request in requests:
        assert "super-secret-token" not in str(request.url)
        assert (
            request.headers["authorization"]
            == "Bearer super-secret-token"
        )

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={
                "detail": "secret provider diagnostics",
            },
        )

    with FrigateHttpAdapter(
        base_url="http://frigate.local",
        bearer_token="super-secret-token",
        transport=httpx.MockTransport(failing),
    ) as adapter:
        try:
            adapter.events()
        except FrigateIntegrationError as exc:
            rendered = str(exc)
            assert "secret provider diagnostics" not in rendered
            assert "super-secret-token" not in rendered
            assert exc.code == "frigate_request_failed"
        else:
            raise AssertionError("expected FrigateIntegrationError")
