from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.integrations.apprise import (
    AppriseAdapter,
    AppriseIntegrationError,
)
from app.integrations.smtp import (
    SmtpAdapter,
    SmtpIntegrationError,
)
from app.modules.alerts.models import Alert
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import (
    get_effective_camera_scope,
    require_permission,
)
from app.modules.auth.service import AuthContext

from .models import NotificationDelivery, NotificationTarget
from .schemas import (
    NotificationDeliveryView,
    NotificationTargetCreate,
    NotificationTargetTestRequest,
    NotificationTargetTestView,
    NotificationTargetUpdate,
    NotificationTargetView,
    SecurityEmailTargetUpdate,
    SecurityEmailTargetView,
)
from .service import NotificationTargetService


router = APIRouter()


def _target_view(
    target: NotificationTarget,
) -> NotificationTargetView:
    return NotificationTargetView(
        id=target.id,
        name=target.name,
        kind=target.kind,
        enabled=target.enabled,
        config=target.config_json or {},
        url_configured=(
            target.kind == "apprise"
            and bool(target.secret_ref)
        ),
        credentials_configured=(
            target.kind == "smtp"
            and bool(target.secret_ref)
        ),
    )


def _target_snapshot(
    target: NotificationTarget,
) -> dict[str, Any]:
    return {
        "name": target.name,
        "kind": target.kind,
        "enabled": target.enabled,
        "config": target.config_json or {},
        "url_configured": (
            target.kind == "apprise"
            and bool(target.secret_ref)
        ),
        "credentials_configured": (
            target.kind == "smtp"
            and bool(target.secret_ref)
        ),
    }


def _delivery_view(
    delivery: NotificationDelivery,
) -> NotificationDeliveryView:
    return NotificationDeliveryView(
        id=delivery.id,
        alert_id=delivery.alert_id,
        purpose=delivery.purpose,
        notification_target_id=delivery.notification_target_id,
        state=delivery.state,
        attempt_count=delivery.attempt_count,
        title=delivery.title,
        body=delivery.body,
        last_attempt_at=delivery.last_attempt_at,
        sent_at=delivery.sent_at,
        last_error_code=delivery.last_error_code,
        provider_message_id=delivery.provider_message_id,
        correlation_id=delivery.correlation_id,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
    )


@router.get(
    "/notification-targets",
    response_model=list[NotificationTargetView],
)
def list_notification_targets(
    _context: AuthContext = Depends(
        require_permission("notification.view")
    ),
    session: Session = Depends(get_db_session),
) -> list[NotificationTargetView]:
    return [
        _target_view(item)
        for item in NotificationTargetService.list(
            session
        )
    ]


@router.post(
    "/notification-targets",
    response_model=NotificationTargetView,
    status_code=201,
)
def create_notification_target(
    body: NotificationTargetCreate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("notification.manage")
    ),
    session: Session = Depends(get_db_session),
) -> NotificationTargetView:
    service = NotificationTargetService(
        request.app.state.settings
    )
    try:
        if body.kind == "smtp":
            if body.url is not None:
                raise ApiError(
                    status_code=400,
                    code="smtp_url_not_allowed",
                    message=(
                        "SMTP targets use structured "
                        "configuration instead of an Apprise URL."
                    ),
                )
            smtp_credentials = None
            if body.smtp_credentials is not None:
                smtp_credentials = {
                    "username": body.smtp_credentials.username,
                    "password": (
                        body.smtp_credentials.password
                        .get_secret_value()
                    ),
                }
            target = service.create_smtp(
                session,
                name=body.name,
                enabled=body.enabled,
                config=body.config,
                credentials=smtp_credentials,
            )
        else:
            if body.smtp_credentials is not None:
                raise ApiError(
                    status_code=400,
                    code="notification_credentials_not_allowed",
                    message=(
                        "Apprise targets do not use "
                        "structured SMTP credentials."
                    ),
                )
            if body.url is None:
                raise ApiError(
                    status_code=400,
                    code="notification_url_required",
                    message="Apprise target URL is required.",
                )
            target = service.create(
                session,
                name=body.name,
                enabled=body.enabled,
                config=body.config,
                url=body.url.get_secret_value(),
            )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="notification_target.create",
            resource_type="notification_target",
            resource_id=target.id,
            after=_target_snapshot(target),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _target_view(target)


@router.get(
    "/notification-targets/security-email-default",
    response_model=SecurityEmailTargetView,
)
def get_security_email_target(
    _context: AuthContext = Depends(
        require_permission("notification.view")
    ),
    session: Session = Depends(get_db_session),
) -> SecurityEmailTargetView:
    return SecurityEmailTargetView(
        target_id=(
            NotificationTargetService
            .security_email_target_id(session)
        )
    )


@router.put(
    "/notification-targets/security-email-default",
    response_model=SecurityEmailTargetView,
)
def set_security_email_target(
    body: SecurityEmailTargetUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("notification.manage")
    ),
    session: Session = Depends(get_db_session),
) -> SecurityEmailTargetView:
    before = (
        NotificationTargetService
        .security_email_target_id(session)
    )
    try:
        target_id = (
            NotificationTargetService
            .set_security_email_target(
                session,
                target_id=body.target_id,
            )
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="notification.security_email_target.update",
            resource_type="system_setting",
            metadata={
                "before_target_id": (
                    str(before)
                    if before is not None
                    else None
                ),
                "after_target_id": (
                    str(target_id)
                    if target_id is not None
                    else None
                ),
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return SecurityEmailTargetView(
        target_id=target_id
    )


@router.get(
    "/notification-targets/{target_id}",
    response_model=NotificationTargetView,
)
def get_notification_target(
    target_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_permission("notification.view")
    ),
    session: Session = Depends(get_db_session),
) -> NotificationTargetView:
    return _target_view(
        NotificationTargetService.get(
            session,
            target_id,
        )
    )


@router.patch(
    "/notification-targets/{target_id}",
    response_model=NotificationTargetView,
)
def update_notification_target(
    target_id: uuid.UUID,
    body: NotificationTargetUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("notification.manage")
    ),
    session: Session = Depends(get_db_session),
) -> NotificationTargetView:
    service = NotificationTargetService(
        request.app.state.settings
    )
    target = service.get(session, target_id)
    before = _target_snapshot(target)

    changes = body.model_dump(
        exclude_unset=True,
        exclude={
            "url",
            "smtp_credentials",
        },
    )

    if target.kind == "smtp":
        if (
            body.url is not None
            or body.url_action != "keep"
        ):
            raise ApiError(
                status_code=400,
                code="smtp_url_not_allowed",
                message=(
                    "SMTP targets do not use "
                    "Apprise URL updates."
                ),
            )
        action = body.credentials_action
        has_credentials = (
            body.smtp_credentials is not None
        )
        if (
            action == "replace"
            and not has_credentials
        ):
            raise ApiError(
                status_code=400,
                code="smtp_credentials_update_invalid",
                message=(
                    "SMTP credential replacement "
                    "requires credentials."
                ),
            )
        if (
            action != "replace"
            and has_credentials
        ):
            raise ApiError(
                status_code=400,
                code="smtp_credentials_update_invalid",
                message=(
                    "SMTP credentials are only accepted "
                    "with action=replace."
                ),
            )
        changes["credentials_action"] = action
        if body.smtp_credentials is not None:
            changes["smtp_credentials"] = {
                "username": (
                    body.smtp_credentials.username
                ),
                "password": (
                    body.smtp_credentials.password
                    .get_secret_value()
                ),
            }
    else:
        if (
            body.smtp_credentials is not None
            or body.credentials_action != "keep"
        ):
            raise ApiError(
                status_code=400,
                code="notification_credentials_not_allowed",
                message=(
                    "Apprise targets do not use "
                    "structured SMTP credentials."
                ),
            )
        url_action = body.url_action
        has_url_value = body.url is not None
        if (
            url_action == "replace"
            and not has_url_value
        ):
            raise ApiError(
                status_code=400,
                code="notification_url_update_invalid",
                message=(
                    "Notification URL replacement "
                    "requires a new value."
                ),
            )
        if (
            url_action != "replace"
            and has_url_value
        ):
            raise ApiError(
                status_code=400,
                code="notification_url_update_invalid",
                message=(
                    "Notification URL value is only "
                    "accepted with action=replace."
                ),
            )
        changes["url_action"] = url_action
        if has_url_value:
            changes["url"] = (
                body.url.get_secret_value()
            )

    try:
        if target.kind == "smtp":
            target = service.update_smtp(
                session,
                target=target,
                changes=changes,
            )
        else:
            target = service.update(
                session,
                target=target,
                changes=changes,
            )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="notification_target.update",
            resource_type="notification_target",
            resource_id=target.id,
            before=before,
            after=_target_snapshot(target),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _target_view(target)


@router.delete(
    "/notification-targets/{target_id}",
    status_code=204,
)
def delete_notification_target(
    target_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("notification.manage")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    service = NotificationTargetService(
        request.app.state.settings
    )
    target = service.get(session, target_id)
    before = _target_snapshot(target)
    resource_id = target.id

    try:
        service.delete(
            session,
            target=target,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="notification_target.delete",
            resource_type="notification_target",
            resource_id=resource_id,
            before=before,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return Response(status_code=204)


@router.post(
    "/notification-targets/{target_id}/test",
    response_model=NotificationTargetTestView,
)
def test_notification_target(
    target_id: uuid.UUID,
    request: Request,
    body: NotificationTargetTestRequest | None = None,
    _context: AuthContext = Depends(
        require_permission("notification.manage")
    ),
    session: Session = Depends(get_db_session),
) -> NotificationTargetTestView:
    service = NotificationTargetService(
        request.app.state.settings
    )
    target = service.get(session, target_id)

    if target.kind == "smtp":
        resolved_smtp = service.resolve_smtp(
            session,
            target=target,
        )
        session.commit()
        try:
            adapter = SmtpAdapter(
                host=resolved_smtp.host,
                port=resolved_smtp.port,
                security=resolved_smtp.security,
                from_address=resolved_smtp.from_address,
                from_name=resolved_smtp.from_name,
                username=resolved_smtp.username,
                password=resolved_smtp.password,
            )
            if (
                body is not None
                and body.recipient is not None
            ):
                adapter.send_test_email(
                    recipient=str(body.recipient),
                )
            else:
                adapter.test_connection()
        except SmtpIntegrationError as exc:
            raise ApiError(
                status_code=exc.status_code,
                code=exc.code,
                message=str(exc),
            ) from exc
        return NotificationTargetTestView()

    if (
        body is not None
        and body.recipient is not None
    ):
        raise ApiError(
            status_code=400,
            code="notification_test_recipient_not_supported",
            message=(
                "A test recipient is only supported "
                "for SMTP targets."
            ),
        )

    resolved = service.resolve(
        session,
        target=target,
    )
    session.commit()

    try:
        AppriseAdapter(
            url=resolved.url
        ).notify(
            title="zero-nvr notification test",
            body="This is a zero-nvr notification target test.",
            notify_type=resolved.notify_type,
        )
    except AppriseIntegrationError as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
        ) from exc

    return NotificationTargetTestView()


@router.get(
    "/notification-deliveries",
    response_model=list[NotificationDeliveryView],
)
def list_notification_deliveries(
    alert_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    limit: int = 100,
    context: AuthContext = Depends(
        require_permission("notification.view")
    ),
    session: Session = Depends(get_db_session),
) -> list[NotificationDeliveryView]:
    if limit < 1 or limit > 500:
        raise ApiError(
            status_code=400,
            code="notification_delivery_limit_invalid",
            message="Notification delivery limit is invalid.",
        )

    scope = get_effective_camera_scope(
        context,
        session,
    )
    statement = (
        select(NotificationDelivery)
        .outerjoin(
            Alert,
            NotificationDelivery.alert_id
            == Alert.id,
        )
    )

    has_system_view = (
        "system.view"
        in context.permissions
    )
    if not (
        scope.all_cameras
        and has_system_view
    ):
        visible = []
        if scope.all_cameras:
            visible.append(
                Alert.camera_id.is_not(None)
            )
        elif scope.camera_ids:
            visible.append(
                Alert.camera_id.in_(
                    scope.camera_ids
                )
            )

        if has_system_view:
            visible.extend(
                [
                    and_(
                        Alert.id.is_not(None),
                        Alert.camera_id.is_(None),
                    ),
                    NotificationDelivery.alert_id.is_(None),
                ]
            )

        statement = statement.where(
            or_(*visible)
            if visible
            else false()
        )

    if alert_id is not None:
        statement = statement.where(
            NotificationDelivery.alert_id
            == alert_id
        )
    if target_id is not None:
        statement = statement.where(
            NotificationDelivery.notification_target_id
            == target_id
        )

    rows = list(
        session.scalars(
            statement.order_by(
                NotificationDelivery.created_at.desc(),
                NotificationDelivery.id.desc(),
            ).limit(limit)
        )
    )
    return [
        _delivery_view(item)
        for item in rows
    ]
