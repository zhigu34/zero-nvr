from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from app.core.config import Settings
from app.core.db import Base, Database
from app.core.security import SecretStore
from app.integrations.onvif import (
    OnvifEventRuntime,
    OnvifEventSubscription,
    OnvifEventTarget,
    OnvifIntegrationError,
)
from app.modules.auth.models import SecretRecord  # noqa: F401
from app.modules.cameras.models import (
    Camera,
    Device,
    DeviceCredential,
    DeviceEndpoint,
)


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
