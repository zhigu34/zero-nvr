from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base, Database
from app.core.security import SecretStore
from app.main import create_app
from app.integrations.onvif import (
    OnvifEventRuntime,
    OnvifEventSubscription,
    OnvifEventTarget,
    OnvifIntegrationError,
    normalize_onvif_notification,
)
from app.modules.auth.models import SecretRecord  # noqa: F401
from app.modules.cameras.models import (
    Camera,
    CameraStreamProfile,
    Device,
    DeviceCredential,
    DeviceEndpoint,
)
from app.modules.events.models import Event
from app.modules.events.onvif import OnvifEventIngestService


def settings(
    tmp_path: Path,
) -> Settings:
    return Settings(
        secret_key=(
            "onvif-events-test-secret-key-"
            "32-bytes-minimum"
        ),
        database_url=(
            f"sqlite:///{tmp_path / 'onvif-events.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        onvif_timeout_seconds=1.0,
    )


def test_app_wires_onvif_notifications_into_event_ingest(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings(tmp_path)
    )
    assert (
        app.state.onvif_events
        ._notification_handler
        is not None
    )
    app.state.database.close()


class FakePullPoint:
    def __init__(self) -> None:
        self.calls = []

    async def PullMessages(
        self,
        request,
    ):
        self.calls.append(request)
        return SimpleNamespace(
            NotificationMessage=[
                "first",
                "second",
            ]
        )


class FakeManager:
    def __init__(
        self,
        lost_callback,
    ) -> None:
        self.lost_callback = lost_callback
        self.service = FakePullPoint()
        self.sync_calls = 0
        self.shutdown_calls = 0

    async def set_synchronization_point(
        self,
    ) -> None:
        self.sync_calls += 1

    def get_service(self):
        return self.service

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


class FakeCamera:
    instances = []

    def __init__(
        self,
        *_args,
        **_kwargs,
    ) -> None:
        self.update_calls = 0
        self.close_calls = 0
        self.manager = None
        self.subscription_time = None
        self.__class__.instances.append(
            self
        )

    async def update_xaddrs(self) -> None:
        self.update_calls += 1

    async def create_pullpoint_manager(
        self,
        subscription_time,
        lost_callback,
    ):
        self.subscription_time = (
            subscription_time
        )
        self.manager = FakeManager(
            lost_callback
        )
        return self.manager

    async def close(self) -> None:
        self.close_calls += 1


def test_pullpoint_subscription_uses_library_manager_lifecycle(
    tmp_path: Path,
) -> None:
    FakeCamera.instances = []

    async def run() -> None:
        subscription = (
            OnvifEventSubscription(
                settings(tmp_path),
                host="192.0.2.20",
                port=80,
                username="camera",
                password="secret",
                camera_factory=FakeCamera,
                subscription_seconds=120,
                pull_timeout_seconds=7,
                message_limit=25,
            )
        )
        await subscription.open()
        camera = FakeCamera.instances[-1]
        assert camera.update_calls == 1
        assert (
            camera.subscription_time
            .total_seconds()
            == 120
        )
        assert camera.manager is not None
        assert (
            camera.manager.sync_calls
            == 1
        )

        messages = await subscription.pull()
        assert messages == (
            "first",
            "second",
        )
        request = (
            camera.manager
            .service.calls[-1]
        )
        assert (
            request["MessageLimit"]
            == 25
        )
        assert (
            request["Timeout"]
            .total_seconds()
            == 7
        )

        camera.manager.lost_callback()
        try:
            await subscription.pull()
        except OnvifIntegrationError as exc:
            assert (
                exc.code
                == "onvif_event_subscription_lost"
            )
        else:
            raise AssertionError(
                "lost subscription must be recreated"
            )

        manager = camera.manager
        await subscription.close()
        assert (
            manager.shutdown_calls
            == 1
        )
        assert camera.close_calls == 1

    asyncio.run(run())


def test_event_runtime_loads_one_target_per_active_events_device(
    tmp_path: Path,
) -> None:
    cfg = settings(tmp_path)
    database = Database(cfg)
    database.initialize_runtime()
    Base.metadata.create_all(
        database.engine
    )
    try:
        with database.session() as session:
            device = Device(
                name="ONVIF NVR",
                adapter_type="onvif",
                enabled=True,
                capabilities_json={
                    "onvif_services": [
                        "Media",
                        "Events",
                    ],
                },
            )
            session.add(device)
            session.flush()
            endpoint = DeviceEndpoint(
                device_id=device.id,
                type="onvif",
                host="192.0.2.30",
                port=8080,
                priority=100,
                enabled=True,
                metadata_json={},
            )
            session.add(endpoint)
            session.flush()
            secret_ref = SecretStore(
                cfg
            ).create_json(
                session,
                kind="onvif_credential",
                owner_type="device",
                owner_id=device.id,
                value={
                    "username": "operator",
                    "password": "credential",
                },
            )
            session.add(
                DeviceCredential(
                    device_id=device.id,
                    endpoint_id=endpoint.id,
                    kind="onvif",
                    secret_ref=secret_ref,
                )
            )
            session.add_all(
                [
                    Camera(
                        device_id=device.id,
                        channel_key="one",
                        name="Channel 1",
                        enabled=True,
                        retired_at=None,
                    ),
                    Camera(
                        device_id=device.id,
                        channel_key="two",
                        name="Channel 2",
                        enabled=True,
                        retired_at=None,
                    ),
                ]
            )
            session.commit()

        runtime = OnvifEventRuntime(
            cfg,
            database,
            logger=logging.getLogger(
                "test-onvif-events"
            ),
        )
        targets = runtime._load_targets()
        assert len(targets) == 1
        assert targets[0].host == (
            "192.0.2.30"
        )
        assert targets[0].port == 8080
        assert targets[0].username == (
            "operator"
        )

        with database.session() as session:
            cameras = list(
                session.query(Camera)
            )
            for camera in cameras:
                camera.enabled = False
            session.commit()

        assert runtime._load_targets() == ()
    finally:
        database.close()


class RuntimeFakeSubscription:
    opened = threading.Event()
    closed = threading.Event()
    open_count = 0

    def __init__(
        self,
        _settings,
        **_kwargs,
    ) -> None:
        pass

    async def open(self) -> None:
        self.__class__.open_count += 1
        self.__class__.opened.set()

    async def pull(self):
        await asyncio.sleep(60)
        return ()

    async def close(self) -> None:
        self.__class__.closed.set()


def test_event_runtime_reconfigure_stops_removed_device(
    tmp_path: Path,
) -> None:
    cfg = settings(tmp_path)
    database = Database(cfg)
    database.initialize_runtime()
    Base.metadata.create_all(
        database.engine
    )
    targets = [
        OnvifEventTarget(
            device_id=uuid.uuid4(),
            host="192.0.2.40",
            port=80,
            username="camera",
            password="secret",
        )
    ]
    RuntimeFakeSubscription.opened.clear()
    RuntimeFakeSubscription.closed.clear()
    RuntimeFakeSubscription.open_count = 0

    runtime = OnvifEventRuntime(
        cfg,
        database,
        logger=logging.getLogger(
            "test-onvif-runtime"
        ),
        subscription_factory=(
            RuntimeFakeSubscription
        ),
        target_loader=lambda: tuple(
            targets
        ),
        retry_seconds=0.01,
    )
    try:
        runtime.start()
        assert (
            RuntimeFakeSubscription
            .opened.wait(2.0)
        )

        targets.clear()
        runtime.reconfigure()
        assert (
            RuntimeFakeSubscription
            .closed.wait(2.0)
        )
    finally:
        runtime.stop()
        database.close()


class RetryFakeSubscription:
    second_opened = threading.Event()
    open_count = 0

    def __init__(
        self,
        _settings,
        **_kwargs,
    ) -> None:
        pass

    async def open(self) -> None:
        self.__class__.open_count += 1
        if self.__class__.open_count >= 2:
            self.__class__.second_opened.set()

    async def pull(self):
        if self.__class__.open_count == 1:
            raise OnvifIntegrationError(
                "onvif_event_subscription_lost",
                "lost",
                status_code=503,
            )
        await asyncio.sleep(60)
        return ()

    async def close(self) -> None:
        return None


def test_event_runtime_recreates_lost_subscription(
    tmp_path: Path,
) -> None:
    cfg = settings(tmp_path)
    database = Database(cfg)
    database.initialize_runtime()
    Base.metadata.create_all(
        database.engine
    )
    RetryFakeSubscription.second_opened.clear()
    RetryFakeSubscription.open_count = 0
    target = OnvifEventTarget(
        device_id=uuid.uuid4(),
        host="192.0.2.50",
        port=80,
        username="camera",
        password="secret",
    )
    runtime = OnvifEventRuntime(
        cfg,
        database,
        logger=logging.getLogger(
            "test-onvif-retry"
        ),
        subscription_factory=(
            RetryFakeSubscription
        ),
        target_loader=lambda: (
            target,
        ),
        retry_seconds=0.01,
    )
    try:
        runtime.start()
        deadline = time.monotonic() + 2.0
        while (
            not RetryFakeSubscription
            .second_opened.is_set()
            and time.monotonic()
            < deadline
        ):
            time.sleep(0.01)
        assert (
            RetryFakeSubscription
            .second_opened.is_set()
        )
    finally:
        runtime.stop()
        database.close()


def _motion_notification(
    *,
    source_token: str,
    active: bool,
    occurred_at: datetime,
):
    return SimpleNamespace(
        Topic=SimpleNamespace(
            _value_1=(
                "tns1:RuleEngine/CellMotionDetector/Motion"
            )
        ),
        Message=SimpleNamespace(
            Message=SimpleNamespace(
                UtcTime=occurred_at,
                PropertyOperation="Changed",
                Source=SimpleNamespace(
                    SimpleItem=[
                        SimpleNamespace(
                            Name=(
                                "VideoSourceConfigurationToken"
                            ),
                            Value=source_token,
                        )
                    ]
                ),
                Data=SimpleNamespace(
                    SimpleItem=[
                        SimpleNamespace(
                            Name="IsMotion",
                            Value=(
                                "true"
                                if active
                                else "false"
                            ),
                        )
                    ]
                ),
            )
        ),
    )


def test_onvif_notification_normalizes_motion_state() -> None:
    occurred_at = datetime(
        2026,
        9,
        23,
        10,
        30,
        tzinfo=UTC,
    )
    normalized = normalize_onvif_notification(
        _motion_notification(
            source_token="source-2",
            active=True,
            occurred_at=occurred_at,
        )
    )

    assert normalized is not None
    assert normalized.category == "motion"
    assert normalized.label == "motion"
    assert normalized.state is True
    assert normalized.occurred_at == occurred_at
    assert normalized.source_items == {
        "VideoSourceConfigurationToken": "source-2"
    }
    assert normalized.data_items == {
        "IsMotion": "true"
    }
    assert normalized.source_event_id.startswith(
        "notification:"
    )


def test_onvif_ingest_maps_channel_and_upserts_motion_lifecycle(
    tmp_path: Path,
) -> None:
    cfg = settings(tmp_path)
    database = Database(cfg)
    database.initialize_runtime()
    Base.metadata.create_all(
        database.engine
    )

    try:
        with database.session() as session:
            device = Device(
                name="Two-channel recorder",
                adapter_type="onvif",
                enabled=True,
                capabilities_json={
                    "onvif_services": [
                        "Events",
                    ],
                },
            )
            session.add(device)
            session.flush()
            first = Camera(
                device_id=device.id,
                channel_key="source-1",
                name="Channel 1",
                enabled=True,
            )
            second = Camera(
                device_id=device.id,
                channel_key="source-2",
                name="Channel 2",
                enabled=True,
            )
            session.add_all(
                [first, second]
            )
            session.flush()
            session.add(
                CameraStreamProfile(
                    camera_id=second.id,
                    adapter_profile_key=(
                        "profile-source-2"
                    ),
                    video_source_key="source-2",
                    name="Main",
                    codec="h264",
                    has_audio=False,
                    status="verified",
                    metadata_json={},
                )
            )
            session.commit()
            device_id = device.id
            second_id = second.id

        logger = logging.getLogger(
            "test-onvif-event-ingest"
        )
        service = OnvifEventIngestService(
            database,
            logger=logger,
        )
        started = datetime(
            2026,
            9,
            23,
            10,
            31,
            tzinfo=UTC,
        )
        start_notification = (
            _motion_notification(
                source_token="source-2",
                active=True,
                occurred_at=started,
            )
        )
        service.handle(
            device_id,
            (
                start_notification,
                start_notification,
            ),
        )

        with database.session() as session:
            assert session.scalar(
                select(func.count())
                .select_from(Event)
            ) == 1
            event = session.scalar(
                select(Event)
            )
            assert event is not None
            assert event.source == "onvif"
            assert event.camera_id == second_id
            assert event.category == "motion"
            assert event.label == "motion"
            assert event.started_at == started
            assert event.ended_at is None
            event_id = event.id
            source_event_id = (
                event.source_event_id
            )

        ended = started + timedelta(
            seconds=9
        )
        end_notification = (
            _motion_notification(
                source_token="source-2",
                active=False,
                occurred_at=ended,
            )
        )
        service.handle(
            device_id,
            (
                end_notification,
                end_notification,
            ),
        )

        with database.session() as session:
            assert session.scalar(
                select(func.count())
                .select_from(Event)
            ) == 1
            event = session.get(
                Event,
                event_id,
            )
            assert event is not None
            assert (
                event.source_event_id
                == source_event_id
            )
            assert event.ended_at == ended
            assert event.metadata_json[
                "state"
            ] is False

        replay_result = service.handle(
            device_id,
            (start_notification,),
        )
        assert replay_result.created == 0
        assert replay_result.updated == 1

        with database.session() as session:
            event = session.get(
                Event,
                event_id,
            )
            assert event is not None
            assert event.ended_at == ended
            assert event.metadata_json[
                "replayed_after_close"
            ] is True
    finally:
        database.close()


def test_onvif_ingest_does_not_guess_multichannel_camera(
    tmp_path: Path,
) -> None:
    cfg = settings(tmp_path)
    database = Database(cfg)
    database.initialize_runtime()
    Base.metadata.create_all(
        database.engine
    )

    try:
        with database.session() as session:
            device = Device(
                name="Two-channel recorder",
                adapter_type="onvif",
                enabled=True,
                capabilities_json={},
            )
            session.add(device)
            session.flush()
            session.add_all(
                [
                    Camera(
                        device_id=device.id,
                        channel_key="source-1",
                        name="Channel 1",
                        enabled=True,
                    ),
                    Camera(
                        device_id=device.id,
                        channel_key="source-2",
                        name="Channel 2",
                        enabled=True,
                    ),
                ]
            )
            session.commit()
            device_id = device.id

        notification = SimpleNamespace(
            Topic=SimpleNamespace(
                _value_1=(
                    "tns1:Device/Trigger/DigitalInput"
                )
            ),
            Message=SimpleNamespace(
                Message=SimpleNamespace(
                    UtcTime=datetime(
                        2026,
                        9,
                        23,
                        10,
                        40,
                        tzinfo=UTC,
                    ),
                    Data=SimpleNamespace(
                        SimpleItem=[
                            SimpleNamespace(
                                Name="LogicalState",
                                Value="true",
                            )
                        ]
                    ),
                )
            ),
        )
        OnvifEventIngestService(
            database,
            logger=logging.getLogger(
                "test-onvif-device-event"
            ),
        ).handle(
            device_id,
            (notification,),
        )

        with database.session() as session:
            event = session.scalar(
                select(Event)
            )
            assert event is not None
            assert event.camera_id is None
            assert event.category == (
                "digital_input"
            )
    finally:
        database.close()
