from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.core.security import SecretStore
from app.modules.cameras.models import (
    Camera,
    Device,
    DeviceCredential,
    DeviceEndpoint,
)

from .events import OnvifEventSubscription


@dataclass(frozen=True, slots=True)
class OnvifEventRuntimeStatus:
    device_id: uuid.UUID
    state: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class OnvifEventTarget:
    device_id: uuid.UUID
    host: str
    port: int
    username: str = field(repr=False)
    password: str = field(repr=False)


NotificationHandler = Callable[
    [uuid.UUID, tuple[Any, ...]],
    None | Awaitable[None],
]


class OnvifEventRuntime:
    """Process runtime for ONVIF PullPoint subscription lifecycle.

    One subscription is maintained per ONVIF Device, not per Camera channel.
    python-onvif-zeep-async owns subscription renewal. zero-nvr recreates a
    manager when the library reports subscription loss or a pull fails.
    """

    def __init__(
        self,
        settings: Settings,
        database: Database,
        *,
        logger: logging.Logger,
        subscription_factory: Callable[..., Any] = OnvifEventSubscription,
        notification_handler: NotificationHandler | None = None,
        target_loader: Callable[
            [],
            tuple[OnvifEventTarget, ...],
        ]
        | None = None,
        retry_seconds: float = 5.0,
    ) -> None:
        self.settings = settings
        self.database = database
        self.logger = logger
        self._secret_store = SecretStore(settings)
        self._subscription_factory = subscription_factory
        self._notification_handler = notification_handler
        self._target_loader = (
            target_loader
            if target_loader is not None
            else self._load_targets
        )
        self.retry_seconds = retry_seconds
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._stopping = threading.Event()
        self._states: dict[
            uuid.UUID,
            OnvifEventRuntimeStatus,
        ] = {}

    def status(
        self,
        device_id: uuid.UUID,
    ) -> OnvifEventRuntimeStatus | None:
        with self._lock:
            return self._states.get(
                device_id
            )

    def _set_status(
        self,
        device_id: uuid.UUID,
        *,
        state: str,
        error_code: str | None = None,
    ) -> None:
        with self._lock:
            self._states[
                device_id
            ] = OnvifEventRuntimeStatus(
                device_id=device_id,
                state=state,
                error_code=error_code,
            )

    def _clear_status(
        self,
        device_id: uuid.UUID,
    ) -> None:
        with self._lock:
            self._states.pop(
                device_id,
                None,
            )

    def _load_targets(
        self,
    ) -> tuple[OnvifEventTarget, ...]:
        with self.database.session() as session:
            active_device_ids = {
                value
                for value in session.scalars(
                    select(Camera.device_id).where(
                        Camera.device_id.is_not(None),
                        Camera.enabled.is_(True),
                        Camera.retired_at.is_(None),
                    )
                )
                if value is not None
            }
            if not active_device_ids:
                session.commit()
                return ()

            devices = list(
                session.scalars(
                    select(Device)
                    .where(
                        Device.id.in_(
                            active_device_ids
                        ),
                        Device.adapter_type
                        == "onvif",
                        Device.enabled.is_(True),
                    )
                    .order_by(Device.id)
                )
            )

            targets: list[
                OnvifEventTarget
            ] = []
            for device in devices:
                services = {
                    str(item).casefold()
                    for item in (
                        device.capabilities_json
                        or {}
                    ).get(
                        "onvif_services",
                        [],
                    )
                    if isinstance(item, str)
                }
                if "events" not in services:
                    continue

                endpoint = next(
                    (
                        item
                        for item in sorted(
                            device.endpoints,
                            key=lambda value: (
                                value.priority,
                                str(value.id),
                            ),
                        )
                        if (
                            item.type == "onvif"
                            and item.enabled
                        )
                    ),
                    None,
                )
                if endpoint is None:
                    continue

                credential = next(
                    (
                        item
                        for item in device.credentials
                        if (
                            item.kind == "onvif"
                            and item.endpoint_id
                            == endpoint.id
                        )
                    ),
                    None,
                )
                if credential is None:
                    credential = next(
                        (
                            item
                            for item
                            in device.credentials
                            if item.kind == "onvif"
                        ),
                        None,
                    )
                if credential is None:
                    continue

                try:
                    secret = (
                        self._secret_store
                        .read_json(
                            session,
                            credential.secret_ref,
                            kind=(
                                "onvif_credential"
                            ),
                            owner_type="device",
                            owner_id=device.id,
                        )
                    )
                except Exception:
                    self.logger.warning(
                        "ONVIF event credential is unavailable",
                        extra={
                            "device_id": str(
                                device.id
                            ),
                        },
                    )
                    continue

                username = secret.get("username")
                password = secret.get("password")
                if (
                    not isinstance(
                        username,
                        str,
                    )
                    or not isinstance(
                        password,
                        str,
                    )
                ):
                    continue

                targets.append(
                    OnvifEventTarget(
                        device_id=device.id,
                        host=endpoint.host,
                        port=(
                            endpoint.port
                            or 80
                        ),
                        username=username,
                        password=password,
                    )
                )

            session.commit()
            return tuple(targets)

    def start(self) -> None:
        with self._lock:
            if (
                self._thread is not None
                and self._thread.is_alive()
            ):
                return
            self._stopping.clear()
            thread = threading.Thread(
                target=self._thread_main,
                name=(
                    "zero-nvr-onvif-events"
                ),
                daemon=True,
            )
            self._thread = thread
        thread.start()

    def reconfigure(self) -> None:
        with self._lock:
            loop = self._loop
            wake = self._wake
        if (
            loop is not None
            and wake is not None
            and not loop.is_closed()
        ):
            loop.call_soon_threadsafe(
                wake.set
            )

    def stop(self) -> None:
        self._stopping.set()
        self.reconfigure()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=10.0)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception:
            self.logger.exception(
                "ONVIF event runtime stopped unexpectedly"
            )
        finally:
            with self._lock:
                self._thread = None
                self._loop = None
                self._wake = None

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        wake = asyncio.Event()
        with self._lock:
            self._loop = loop
            self._wake = wake

        tasks: dict[
            uuid.UUID,
            tuple[
                OnvifEventTarget,
                asyncio.Task[None],
            ],
        ] = {}

        async def reconcile() -> None:
            desired = {
                target.device_id: target
                for target
                in self._target_loader()
            }

            stale = [
                device_id
                for device_id, (
                    target,
                    _task,
                ) in tasks.items()
                if (
                    device_id
                    not in desired
                    or desired[
                        device_id
                    ] != target
                )
            ]
            for device_id in stale:
                _target, task = (
                    tasks.pop(
                        device_id
                    )
                )
                task.cancel()
                await asyncio.gather(
                    task,
                    return_exceptions=True,
                )
                self._clear_status(
                    device_id
                )

            for (
                device_id,
                target,
            ) in desired.items():
                if device_id in tasks:
                    continue
                self._set_status(
                    device_id,
                    state="starting",
                )
                task = asyncio.create_task(
                    self._run_target(
                        target
                    )
                )
                tasks[device_id] = (
                    target,
                    task,
                )

        try:
            await reconcile()
            while not self._stopping.is_set():
                await wake.wait()
                wake.clear()
                if self._stopping.is_set():
                    break
                await reconcile()
        finally:
            for _target, task in (
                tasks.values()
            ):
                task.cancel()
            if tasks:
                await asyncio.gather(
                    *(
                        task
                        for _target, task
                        in tasks.values()
                    ),
                    return_exceptions=True,
                )
            for device_id in tuple(
                tasks
            ):
                self._clear_status(
                    device_id
                )

    async def _run_target(
        self,
        target: OnvifEventTarget,
    ) -> None:
        while not self._stopping.is_set():
            subscription = (
                self._subscription_factory(
                    self.settings,
                    host=target.host,
                    port=target.port,
                    username=target.username,
                    password=target.password,
                )
            )
            try:
                await subscription.open()
                self._set_status(
                    target.device_id,
                    state="healthy",
                )
                while (
                    not self._stopping
                    .is_set()
                ):
                    notifications = (
                        await subscription.pull()
                    )
                    if (
                        notifications
                        and self._notification_handler
                        is not None
                    ):
                        result = (
                            self._notification_handler(
                                target.device_id,
                                notifications,
                            )
                        )
                        if inspect.isawaitable(
                            result
                        ):
                            await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._set_status(
                    target.device_id,
                    state="degraded",
                    error_code=(
                        getattr(
                            exc,
                            "code",
                            None,
                        )
                        or "onvif_event_subscription_failed"
                    ),
                )
                self.logger.warning(
                    "ONVIF event subscription will be recreated",
                    extra={
                        "device_id": str(
                            target.device_id
                        ),
                    },
                )
            finally:
                await subscription.close()

            if self._stopping.is_set():
                break
            await asyncio.sleep(
                self.retry_seconds
            )
