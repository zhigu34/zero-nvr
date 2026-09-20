from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Callable

from app.core.config import Settings
from app.core.db import Database
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.integrations.apprise import (
    AppriseAdapter,
    AppriseIntegrationError,
)

from .models import NotificationDelivery, NotificationTarget
from .service import NotificationTargetService


@dataclass(frozen=True, slots=True)
class NotificationPlan:
    delivery_id: uuid.UUID
    target_id: uuid.UUID
    title: str
    body: str
    notify_type: str
    url: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class NotificationResult:
    delivery_id: uuid.UUID
    state: str
    delivered: bool


class NotificationDeliveryService:
    def __init__(
        self,
        settings: Settings,
        *,
        adapter_factory: Callable[..., AppriseAdapter] = AppriseAdapter,
    ) -> None:
        self.settings = settings
        self._adapter_factory = adapter_factory

    def prepare(
        self,
        database: Database,
        *,
        delivery_id: uuid.UUID,
    ) -> NotificationPlan | NotificationResult:
        with database.session() as session:
            delivery = session.get(
                NotificationDelivery,
                delivery_id,
            )
            if delivery is None:
                raise ApiError(
                    status_code=404,
                    code="notification_delivery_not_found",
                    message="Notification delivery was not found.",
                )

            if delivery.state == "SENT":
                session.commit()
                return NotificationResult(
                    delivery_id=delivery.id,
                    state="SENT",
                    delivered=False,
                )
            if delivery.state == "SKIPPED":
                session.commit()
                return NotificationResult(
                    delivery_id=delivery.id,
                    state="SKIPPED",
                    delivered=False,
                )

            target = session.get(
                NotificationTarget,
                delivery.notification_target_id,
            )
            if target is None or not target.enabled:
                delivery.state = "SKIPPED"
                delivery.last_attempt_at = utc_now()
                delivery.last_error_code = (
                    "notification_target_unavailable"
                )
                session.commit()
                return NotificationResult(
                    delivery_id=delivery.id,
                    state="SKIPPED",
                    delivered=False,
                )

            if (
                delivery.state == "SENDING"
                and delivery.last_attempt_at is not None
                and delivery.last_attempt_at
                > datetime.now(UTC) - timedelta(minutes=5)
            ):
                session.commit()
                raise ApiError(
                    status_code=409,
                    code="notification_delivery_busy",
                    message="Notification delivery is already in progress.",
                )

            resolved = NotificationTargetService(
                self.settings
            ).resolve(
                session,
                target=target,
            )

            delivery.state = "SENDING"
            delivery.attempt_count += 1
            delivery.last_attempt_at = utc_now()
            delivery.last_error_code = None
            plan = NotificationPlan(
                delivery_id=delivery.id,
                target_id=target.id,
                title=delivery.title,
                body=delivery.body,
                notify_type=resolved.notify_type,
                url=resolved.url,
            )
            session.commit()
            return plan

    @staticmethod
    def _mark_failed(
        database: Database,
        *,
        delivery_id: uuid.UUID,
        error_code: str,
    ) -> None:
        with database.session() as session:
            delivery = session.get(
                NotificationDelivery,
                delivery_id,
            )
            if delivery is not None:
                delivery.state = "FAILED"
                delivery.last_attempt_at = utc_now()
                delivery.last_error_code = error_code
                session.commit()

    @staticmethod
    def _mark_sent(
        database: Database,
        *,
        delivery_id: uuid.UUID,
    ) -> None:
        with database.session() as session:
            delivery = session.get(
                NotificationDelivery,
                delivery_id,
            )
            if delivery is None:
                raise ApiError(
                    status_code=404,
                    code="notification_delivery_not_found",
                    message="Notification delivery disappeared after send.",
                )
            delivery.state = "SENT"
            delivery.sent_at = utc_now()
            delivery.last_attempt_at = utc_now()
            delivery.last_error_code = None
            session.commit()

    def execute(
        self,
        database: Database,
        *,
        delivery_id: uuid.UUID,
    ) -> NotificationResult:
        prepared = self.prepare(
            database,
            delivery_id=delivery_id,
        )
        if isinstance(prepared, NotificationResult):
            return prepared

        try:
            self._adapter_factory(
                url=prepared.url
            ).notify(
                title=prepared.title,
                body=prepared.body,
                notify_type=prepared.notify_type,
            )
        except AppriseIntegrationError as exc:
            self._mark_failed(
                database,
                delivery_id=prepared.delivery_id,
                error_code=exc.code,
            )
            raise

        self._mark_sent(
            database,
            delivery_id=prepared.delivery_id,
        )
        return NotificationResult(
            delivery_id=prepared.delivery_id,
            state="SENT",
            delivered=True,
        )
