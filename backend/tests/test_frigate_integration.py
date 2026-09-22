from __future__ import annotations

import logging
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base, Database
from app.integrations.frigate import (
    FrigateEventNormalizer,
    FrigateHttpAdapter,
    FrigateIntegrationError,
    FrigateMqttRuntime,
)
from app.modules.auth.models import SecretRecord
from app.modules.cameras.service import CameraService
from app.modules.events.frigate import FrigateEventIngestService
from app.modules.events.models import Event
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingTrigger,
)
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
                credentials_action="replace",
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
                credentials_action="keep",
            )
            session.commit()
            assert updated.instance_id == first_id
            assert (
                updated.credentials.http_bearer_token
                == "http-secret-token"
            )

            cleared = service.put(
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
                credentials_action="clear",
            )
            session.commit()
            assert cleared.instance_id == first_id
            assert cleared.credentials == FrigateCredentials()
            assert session.scalar(
                select(func.count()).select_from(
                    SecretRecord
                ).where(
                    SecretRecord.kind
                    == "frigate_credentials"
                )
            ) == 0
    finally:
        database.close()


def test_http_adapter_sanitizes_errors_and_fetches_events() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/version":
            return httpx.Response(
                200,
                text="0.16.0",
                headers={"content-type": "text/plain"},
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



def test_frigate_event_filter_drives_one_idempotent_recording_trigger(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id = seed_camera(settings, database)
        service = FrigateProviderSettingsService(settings)

        with database.session() as session:
            session.add(
                RecordingPolicy(
                    camera_id=camera_id,
                    baseline_mode="disabled",
                    event_recording_enabled=True,
                    event_filter_json={
                        "labels": ["person"],
                        "zones": ["yard"],
                        "min_confidence": 0.9,
                    },
                    pre_roll_seconds=10,
                    post_roll_seconds=15,
                    enabled=True,
                )
            )
            config = service.put(
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
            config = service.get(session)
            assert config is not None
            started = FrigateEventIngestService.mqtt(
                session,
                config=config,
                payload=mqtt_payload(),
            )
            assert started.trigger is not None
            assert started.trigger_changed is True
            trigger_id = started.trigger.id
            assert started.trigger.state == "ACTIVE"
            assert started.trigger.planned_start_at == datetime.fromtimestamp(
                1_699_999_990.0,
                tz=UTC,
            )
            assert started.trigger.planned_end_at is None
            session.commit()

        with database.session() as session:
            config = service.get(session)
            assert config is not None
            duplicate = FrigateEventIngestService.mqtt(
                session,
                config=config,
                payload=mqtt_payload(
                    message_type="update",
                ),
            )
            assert duplicate.trigger is not None
            assert duplicate.trigger.id == trigger_id
            assert duplicate.trigger_changed is False
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
            assert ended.trigger is not None
            assert ended.trigger.id == trigger_id
            assert ended.trigger.state == "COMPLETED"
            assert ended.trigger.planned_end_at == datetime.fromtimestamp(
                1_700_000_045.0,
                tz=UTC,
            )
            assert ended.trigger_changed is True
            session.commit()

            triggers = list(
                session.scalars(
                    select(RecordingTrigger)
                )
            )
            assert len(triggers) == 1
            assert triggers[0].source == "frigate"
            assert triggers[0].source_event_id == (
                f"{config.instance_id}:event-1"
            )

        with database.session() as session:
            config = service.get(session)
            assert config is not None
            filtered_payload = mqtt_payload(
                event_id="event-car",
            )
            filtered_payload["after"]["label"] = "car"
            filtered = FrigateEventIngestService.mqtt(
                session,
                config=config,
                payload=filtered_payload,
            )
            assert filtered.event is not None
            assert filtered.trigger is None
            assert filtered.trigger_changed is False
            session.commit()

            assert len(
                list(session.scalars(select(Event)))
            ) == 2
            assert len(
                list(session.scalars(select(RecordingTrigger)))
            ) == 1
    finally:
        database.close()


class _FakeReasonCode:
    is_failure = False


class _FakeMqttClient:
    instances: list["_FakeMqttClient"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.username = None
        self.password = None
        self.tls = False
        self.connected_to = None
        self.loop_started = False
        self.subscriptions = []
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.instances.append(self)

    def username_pw_set(self, username, password=None) -> None:
        self.username = username
        self.password = password

    def tls_set(self) -> None:
        self.tls = True

    def connect_async(self, host, port, keepalive=60) -> None:
        self.connected_to = (host, port, keepalive)

    def loop_start(self) -> None:
        self.loop_started = True

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        return (0, 1)

    def disconnect(self) -> None:
        return None

    def loop_stop(self) -> None:
        self.loop_started = False


class _FakeRecordingTasks:
    def __init__(self) -> None:
        self.camera_ids = []

    def reconcile_camera(self, camera_id) -> None:
        self.camera_ids.append(camera_id)


def test_mqtt_runtime_uses_persistent_qos1_and_ingests_event(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id = seed_camera(settings, database)
        provider = FrigateProviderSettingsService(settings)
        with database.session() as session:
            session.add(
                RecordingPolicy(
                    camera_id=camera_id,
                    baseline_mode="disabled",
                    event_recording_enabled=True,
                    event_filter_json={},
                    pre_roll_seconds=10,
                    post_roll_seconds=10,
                    enabled=True,
                )
            )
            provider.put(
                session,
                enabled=True,
                mode="external",
                base_url="http://frigate.local",
                camera_map={"front_door": camera_id},
                mqtt_enabled=True,
                mqtt_host="mqtt.local",
                mqtt_port=8883,
                mqtt_topic_prefix="frigate",
                mqtt_tls=True,
                credentials=FrigateCredentials(
                    mqtt_username="mqtt-user",
                    mqtt_password="mqtt-password",
                ),
                credentials_action="replace",
            )
            session.commit()

        _FakeMqttClient.instances = []
        tasks = _FakeRecordingTasks()
        runtime = FrigateMqttRuntime(
            settings,
            database,
            logger=logging.getLogger(
                "test.frigate.mqtt"
            ),
            recording_tasks=tasks,
            client_factory=_FakeMqttClient,
        )

        runtime.start()
        client = _FakeMqttClient.instances[-1]
        assert client.kwargs["clean_session"] is False
        assert client.connected_to == (
            "mqtt.local",
            8883,
            60,
        )
        assert client.username == "mqtt-user"
        assert client.password == "mqtt-password"
        assert client.tls is True

        client.on_connect(
            client,
            None,
            None,
            _FakeReasonCode(),
            None,
        )
        assert client.subscriptions == [
            ("frigate/events", 1)
        ]
        assert runtime.status().connected is True

        message = type(
            "Message",
            (),
            {
                "topic": "frigate/events",
                "payload": json.dumps(
                    mqtt_payload()
                ).encode("utf-8"),
            },
        )()
        client.on_message(
            client,
            None,
            message,
        )

        with database.session() as session:
            events = list(
                session.scalars(select(Event))
            )
            triggers = list(
                session.scalars(
                    select(RecordingTrigger)
                )
            )
            assert len(events) == 1
            assert len(triggers) == 1

        assert tasks.camera_ids == [camera_id]
        runtime.stop()
    finally:
        database.close()
