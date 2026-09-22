from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from app.core.config import Settings
from app.core.db import Database
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.integrations.apprise import (
    AppriseAdapter,
    AppriseIntegrationError,
)
from app.integrations.smtp import (
    SmtpAdapter,
    SmtpIntegrationError,
)

from .models import NotificationDelivery, NotificationTarget
from .service import (
    NotificationTargetService,
    ResolvedSmtpTarget,
)


@dataclass(frozen=True, slots=True)
class NotificationPlan:
    delivery_id: uuid.UUID
    target_id: uuid.UUID
    target_kind: str
    purpose: str
    correlation_id: str | None
    title: str
    body: str
    notify_type: str
    url: str | None = field(
        default=None,
        repr=False,
    )
    smtp: ResolvedSmtpTarget | None = field(
        default=None,
        repr=False,
    )


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
        adapter_factory: Callable[..., Any] = AppriseAdapter,
        smtp_adapter_factory: Callable[..., Any] = SmtpAdapter,
    ) -> None:
        self.settings = settings
        self._adapter_factory = adapter_factory
        self._smtp_adapter_factory = smtp_adapter_factory

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

            if (
                delivery.purpose == "password_reset"
                and not (
                    target.kind == "smtp"
                    or (
                        target.kind == "apprise"
                        and NotificationTargetService
                        .is_password_reset_target(target)
                    )
                )
            ):
                delivery.state = "FAILED"
                delivery.last_attempt_at = utc_now()
                delivery.last_error_code = (
                    "password_reset_target_unavailable"
                )
                session.commit()
                return NotificationResult(
                    delivery_id=delivery.id,
                    state="FAILED",
                    delivered=False,
                )

            target_service = NotificationTargetService(
                self.settings
            )
            resolved_smtp: ResolvedSmtpTarget | None = None
            resolved_url: str | None = None
            notify_type = "info"
            try:
                if target.kind == "smtp":
                    resolved_smtp = (
                        target_service.resolve_smtp(
                            session,
                            target=target,
                        )
                    )
                else:
                    resolved = target_service.resolve(
                        session,
                        target=target,
                    )
                    resolved_url = resolved.url
                    notify_type = resolved.notify_type
            except ApiError as exc:
                delivery.state = "FAILED"
                delivery.last_attempt_at = utc_now()
                delivery.last_error_code = exc.code
                session.commit()
                return NotificationResult(
                    delivery_id=delivery.id,
                    state="FAILED",
                    delivered=False,
                )

            delivery.state = "SENDING"
            delivery.attempt_count += 1
            delivery.last_attempt_at = utc_now()
            delivery.last_error_code = None
            plan = NotificationPlan(
                delivery_id=delivery.id,
                target_id=target.id,
                target_kind=target.kind,
                purpose=delivery.purpose,
                correlation_id=delivery.correlation_id,
                title=delivery.title,
                body=delivery.body,
                notify_type=notify_type,
                url=resolved_url,
                smtp=resolved_smtp,
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

        delivery_url = prepared.url
        delivery_title = prepared.title
        delivery_body = prepared.body
        delivery_recipient: str | None = None

        if prepared.purpose == "password_reset":
            try:
                if not prepared.correlation_id:
                    raise ApiError(
                        status_code=409,
                        code="password_reset_delivery_invalid",
                        message="Password reset delivery is invalid.",
                    )
                from app.modules.auth.password_reset import (
                    PasswordResetService,
                )

                with database.session() as session:
                    mail = PasswordResetService(
                        self.settings
                    ).delivery_mail(
                        session,
                        correlation_id=prepared.correlation_id,
                    )
                delivery_title = mail.title
                delivery_body = mail.body
                delivery_recipient = mail.recipient
                if prepared.target_kind == "apprise":
                    if prepared.url is None:
                        raise ApiError(
                            status_code=409,
                            code="notification_secret_unavailable",
                            message=(
                                "Notification target secret "
                                "is unavailable."
                            ),
                        )
                    delivery_url = (
                        NotificationTargetService
                        .password_reset_recipient_url(
                            prepared.url,
                            mail.recipient,
                        )
                    )
            except ApiError as exc:
                self._mark_failed(
                    database,
                    delivery_id=prepared.delivery_id,
                    error_code=exc.code,
                )
                return NotificationResult(
                    delivery_id=prepared.delivery_id,
                    state="FAILED",
                    delivered=False,
                )

        try:
            if prepared.target_kind == "smtp":
                if (
                    prepared.smtp is None
                    or delivery_recipient is None
                ):
                    raise SmtpIntegrationError(
                        "smtp_recipient_unavailable",
                        "SMTP email recipient is unavailable.",
                        status_code=409,
                        category="permanent",
                    )
                smtp = prepared.smtp
                self._smtp_adapter_factory(
                    host=smtp.host,
                    port=smtp.port,
                    security=smtp.security,
                    from_address=smtp.from_address,
                    from_name=smtp.from_name,
                    username=smtp.username,
                    password=smtp.password,
                ).send_email(
                    recipient=delivery_recipient,
                    title=delivery_title,
                    body=delivery_body,
                )
            else:
                if delivery_url is None:
                    raise AppriseIntegrationError(
                        "notification_secret_unavailable",
                        "Notification target secret is unavailable.",
                        status_code=409,
                        category="permanent",
                    )
                self._adapter_factory(
                    url=delivery_url
                ).notify(
                    title=delivery_title,
                    body=delivery_body,
                    notify_type=prepared.notify_type,
                )
        except (
            AppriseIntegrationError,
            SmtpIntegrationError,
        ) as exc:
            self._mark_failed(
                database,
                delivery_id=prepared.delivery_id,
                error_code=exc.code,
            )
            if exc.category == "permanent":
                return NotificationResult(
                    delivery_id=prepared.delivery_id,
                    state="FAILED",
                    delivered=False,
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
