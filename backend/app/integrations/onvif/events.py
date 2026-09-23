from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Callable

from onvif import ONVIFCamera

from app.core.config import Settings

from .adapter import OnvifIntegrationError


def _read(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


class OnvifEventSubscription:
    """Thin PullPoint lifecycle around python-onvif-zeep-async.

    The library owns CreatePullPointSubscription, renewal and subscription
    manager protocol details. zero-nvr only opens the manager, pulls messages,
    observes subscription loss and shuts the manager down.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        camera_factory: Callable[..., Any] = ONVIFCamera,
        subscription_seconds: int = 300,
        pull_timeout_seconds: int = 15,
        message_limit: int = 100,
    ) -> None:
        self.settings = settings
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._camera_factory = camera_factory
        self.subscription_seconds = subscription_seconds
        self.pull_timeout_seconds = pull_timeout_seconds
        self.message_limit = message_limit
        self._camera: Any | None = None
        self._manager: Any | None = None
        self._lost = False

    def _subscription_lost(self) -> None:
        self._lost = True

    async def open(self) -> None:
        if self._manager is not None:
            return

        camera: Any | None = None
        manager: Any | None = None
        try:
            camera = self._camera_factory(
                self.host,
                self.port,
                self.username,
                self.password,
                nat_override=True,
                no_cache=True,
            )
            async with asyncio.timeout(
                self.settings.onvif_timeout_seconds
            ):
                await camera.update_xaddrs()
                manager = await camera.create_pullpoint_manager(
                    timedelta(
                        seconds=self.subscription_seconds
                    ),
                    self._subscription_lost,
                )
                await manager.set_synchronization_point()

            self._camera = camera
            self._manager = manager
            self._lost = False
        except TimeoutError as exc:
            if manager is not None:
                try:
                    await manager.shutdown()
                except Exception:
                    pass
            if camera is not None:
                try:
                    await camera.close()
                except Exception:
                    pass
            raise OnvifIntegrationError(
                "onvif_event_subscription_timeout",
                "The ONVIF event subscription timed out.",
                status_code=504,
            ) from exc
        except OnvifIntegrationError:
            raise
        except Exception as exc:
            if manager is not None:
                try:
                    await manager.shutdown()
                except Exception:
                    pass
            if camera is not None:
                try:
                    await camera.close()
                except Exception:
                    pass
            raise OnvifIntegrationError(
                "onvif_event_subscription_failed",
                "Unable to create the ONVIF event subscription.",
                status_code=422,
            ) from exc

    async def pull(self) -> tuple[Any, ...]:
        manager = self._manager
        if manager is None:
            raise OnvifIntegrationError(
                "onvif_event_subscription_unavailable",
                "The ONVIF event subscription is not open.",
                status_code=409,
            )
        if self._lost:
            raise OnvifIntegrationError(
                "onvif_event_subscription_lost",
                "The ONVIF event subscription was lost.",
                status_code=503,
            )

        try:
            service = manager.get_service()
            async with asyncio.timeout(
                self.pull_timeout_seconds
                + self.settings.onvif_timeout_seconds
            ):
                response = await service.PullMessages(
                    {
                        "MessageLimit": self.message_limit,
                        "Timeout": timedelta(
                            seconds=self.pull_timeout_seconds
                        ),
                    }
                )
        except TimeoutError as exc:
            raise OnvifIntegrationError(
                "onvif_event_pull_timeout",
                "The ONVIF event pull timed out.",
                status_code=504,
            ) from exc
        except OnvifIntegrationError:
            raise
        except Exception as exc:
            raise OnvifIntegrationError(
                "onvif_event_pull_failed",
                "Unable to pull ONVIF events.",
                status_code=503,
            ) from exc

        notifications = _read(
            response,
            "NotificationMessage",
        )
        if notifications is None:
            return ()
        if isinstance(
            notifications,
            (list, tuple),
        ):
            return tuple(notifications)
        return (notifications,)

    async def close(self) -> None:
        manager = self._manager
        camera = self._camera
        self._manager = None
        self._camera = None
        self._lost = False

        if manager is not None:
            try:
                await manager.shutdown()
            except Exception:
                pass
        if camera is not None:
            try:
                await camera.close()
            except Exception:
                pass

    async def __aenter__(
        self,
    ) -> "OnvifEventSubscription":
        await self.open()
        return self

    async def __aexit__(
        self,
        *_exc: object,
    ) -> None:
        await self.close()
