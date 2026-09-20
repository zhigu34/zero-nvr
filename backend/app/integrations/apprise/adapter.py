from __future__ import annotations

from typing import Any, Callable

from apprise import Apprise, NotifyType


class AppriseIntegrationError(RuntimeError):
    """Sanitized notification delivery failure.

    Never expose notification URLs in raised errors: they commonly embed
    credentials, tokens, recipients, or webhook secrets.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


_NOTIFY_TYPES = {
    "info": NotifyType.INFO,
    "success": NotifyType.SUCCESS,
    "warning": NotifyType.WARNING,
    "failure": NotifyType.FAILURE,
}


class AppriseAdapter:
    def __init__(
        self,
        *,
        url: str,
        apprise_factory: Callable[[], Any] = Apprise,
    ) -> None:
        normalized = url.strip()
        if not normalized:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "Notification target URL is invalid.",
                status_code=400,
            )

        self._apprise = apprise_factory()
        try:
            added = self._apprise.add(normalized)
        except Exception as exc:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "Notification target URL is invalid.",
                status_code=400,
            ) from exc

        if not added:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "Notification target URL is invalid.",
                status_code=400,
            )

    def notify(
        self,
        *,
        title: str,
        body: str,
        notify_type: str = "info",
    ) -> None:
        apprise_type = _NOTIFY_TYPES.get(notify_type)
        if apprise_type is None:
            raise AppriseIntegrationError(
                "notification_type_invalid",
                "Notification type is invalid.",
                status_code=400,
            )

        try:
            delivered = self._apprise.notify(
                body=body,
                title=title,
                notify_type=apprise_type,
            )
        except Exception as exc:
            raise AppriseIntegrationError(
                "notification_delivery_failed",
                "Notification delivery failed.",
            ) from exc

        if delivered is not True:
            raise AppriseIntegrationError(
                "notification_delivery_failed",
                "Notification delivery failed.",
            )
