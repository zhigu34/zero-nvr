from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.integrations.apprise import (
    AppriseAdapter,
    AppriseIntegrationError,
)
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import require_permission
from app.modules.auth.service import AuthContext

from .models import NotificationDelivery, NotificationTarget
from .schemas import (
    NotificationDeliveryView,
    NotificationTargetCreate,
    NotificationTargetTestView,
    NotificationTargetUpdate,
    NotificationTargetView,
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
        url_configured=bool(target.secret_ref),
    )


def _target_snapshot(
    target: NotificationTarget,
) -> dict[str, Any]:
    return {
        "name": target.name,
        "kind": target.kind,
        "enabled": target.enabled,
        "config": target.config_json or {},
        "url_configured": bool(target.secret_ref),
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
        require_permission("alert.manage")
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
        require_permission("alert.manage")
    ),
    session: Session = Depends(get_db_session),
) -> NotificationTargetView:
    service = NotificationTargetService(
        request.app.state.settings
    )
    try:
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
    "/notification-targets/{target_id}",
    response_model=NotificationTargetView,
)
def get_notification_target(
    target_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_permission("alert.manage")
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
        require_permission("alert.manage")
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
        exclude={"url"},
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
        require_permission("alert.manage")
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
    _context: AuthContext = Depends(
        require_permission("alert.manage")
    ),
    session: Session = Depends(get_db_session),
) -> NotificationTargetTestView:
    service = NotificationTargetService(
        request.app.state.settings
    )
    target = service.get(session, target_id)
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
    _context: AuthContext = Depends(
        require_permission("alert.manage")
    ),
    session: Session = Depends(get_db_session),
) -> list[NotificationDeliveryView]:
    if limit < 1 or limit > 500:
        raise ApiError(
            status_code=400,
            code="notification_delivery_limit_invalid",
            message="Notification delivery limit is invalid.",
        )

    statement = select(
        NotificationDelivery
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
