from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import (
    get_effective_camera_scope,
    require_permission,
)
from app.modules.auth.service import AuthContext

from .models import Alert, AlertPolicy
from .query import AlertQueryService
from .schemas import (
    AlertPage,
    AlertPolicyCreate,
    AlertPolicyUpdate,
    AlertPolicyView,
    AlertView,
)
from .service import AlertPolicyService


router = APIRouter()


def _policy_view(
    policy: AlertPolicy,
) -> AlertPolicyView:
    return AlertPolicyView(
        id=policy.id,
        name=policy.name,
        enabled=policy.enabled,
        severity=policy.severity,
        match=policy.match_json or {},
        actions=policy.action_json or {},
        cooldown_seconds=policy.cooldown_seconds,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _policy_snapshot(
    policy: AlertPolicy,
) -> dict[str, Any]:
    return {
        "name": policy.name,
        "enabled": policy.enabled,
        "severity": policy.severity,
        "match": policy.match_json or {},
        "actions": policy.action_json or {},
        "cooldown_seconds": policy.cooldown_seconds,
    }


def _alert_view(alert: Alert) -> AlertView:
    return AlertView(
        id=alert.id,
        policy_id=alert.policy_id,
        event_id=alert.event_id,
        camera_id=alert.camera_id,
        severity=alert.severity,
        title=alert.title,
        message=alert.message,
        state=alert.state,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        resolved_at=alert.resolved_at,
        created_at=alert.created_at,
    )


def _alert_scope(
    context: AuthContext,
    session: Session,
    alert: Alert,
) -> None:
    if alert.camera_id is None:
        if "system.view" not in context.permissions:
            raise ApiError(
                status_code=404,
                code="alert_not_found",
                message="Alert was not found.",
            )
        return
    scope = get_effective_camera_scope(
        context,
        session,
    )
    if not scope.allows(alert.camera_id):
        raise ApiError(
            status_code=404,
            code="alert_not_found",
            message="Alert was not found.",
        )


@router.get(
    "/alert-policies",
    response_model=list[AlertPolicyView],
)
def list_alert_policies(
    _context: AuthContext = Depends(
        require_permission("alert.manage")
    ),
    session: Session = Depends(get_db_session),
) -> list[AlertPolicyView]:
    return [
        _policy_view(item)
        for item in AlertPolicyService.list(session)
    ]


@router.post(
    "/alert-policies",
    response_model=AlertPolicyView,
    status_code=201,
)
def create_alert_policy(
    body: AlertPolicyCreate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("alert.manage")
    ),
    session: Session = Depends(get_db_session),
) -> AlertPolicyView:
    try:
        policy = AlertPolicyService.create(
            session,
            name=body.name,
            enabled=body.enabled,
            severity=body.severity,
            match=body.match,
            actions=body.actions,
            cooldown_seconds=body.cooldown_seconds,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="alert_policy.create",
            resource_type="alert_policy",
            resource_id=policy.id,
            after=_policy_snapshot(policy),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _policy_view(policy)


@router.get(
    "/alert-policies/{policy_id}",
    response_model=AlertPolicyView,
)
def get_alert_policy(
    policy_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_permission("alert.manage")
    ),
    session: Session = Depends(get_db_session),
) -> AlertPolicyView:
    return _policy_view(
        AlertPolicyService.get(
            session,
            policy_id,
        )
    )


@router.patch(
    "/alert-policies/{policy_id}",
    response_model=AlertPolicyView,
)
def update_alert_policy(
    policy_id: uuid.UUID,
    body: AlertPolicyUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("alert.manage")
    ),
    session: Session = Depends(get_db_session),
) -> AlertPolicyView:
    policy = AlertPolicyService.get(
        session,
        policy_id,
    )
    before = _policy_snapshot(policy)
    try:
        policy = AlertPolicyService.update(
            session,
            policy=policy,
            changes=body.model_dump(
                exclude_unset=True
            ),
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="alert_policy.update",
            resource_type="alert_policy",
            resource_id=policy.id,
            before=before,
            after=_policy_snapshot(policy),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _policy_view(policy)


@router.delete(
    "/alert-policies/{policy_id}",
    status_code=204,
)
def delete_alert_policy(
    policy_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("alert.manage")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    policy = AlertPolicyService.get(
        session,
        policy_id,
    )
    before = _policy_snapshot(policy)
    resource_id = policy.id
    try:
        AlertPolicyService.delete(
            session,
            policy=policy,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="alert_policy.delete",
            resource_type="alert_policy",
            resource_id=resource_id,
            before=before,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return Response(status_code=204)


@router.get(
    "/alerts",
    response_model=AlertPage,
)
def list_alerts(
    camera_id: uuid.UUID | None = None,
    state: str | None = None,
    severity: str | None = None,
    cursor: str | None = None,
    limit: int = 100,
    context: AuthContext = Depends(
        require_permission("alert.view")
    ),
    session: Session = Depends(get_db_session),
) -> AlertPage:
    scope = get_effective_camera_scope(
        context,
        session,
    )
    if (
        camera_id is not None
        and not scope.allows(camera_id)
    ):
        raise ApiError(
            status_code=404,
            code="camera_not_found",
            message="Camera was not found.",
        )

    result = AlertQueryService.list(
        session,
        allowed_camera_ids=(
            None
            if scope.all_cameras
            else scope.camera_ids
        ),
        include_system_alerts=(
            "system.view"
            in context.permissions
        ),
        camera_id=camera_id,
        state=state,
        severity=severity,
        cursor=cursor,
        limit=limit,
    )
    return AlertPage(
        items=[
            _alert_view(item)
            for item in result.items
        ],
        next_cursor=result.next_cursor,
    )


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertView,
)
def get_alert(
    alert_id: uuid.UUID,
    context: AuthContext = Depends(
        require_permission("alert.view")
    ),
    session: Session = Depends(get_db_session),
) -> AlertView:
    alert = AlertQueryService.get(
        session,
        alert_id,
    )
    _alert_scope(
        context,
        session,
        alert,
    )
    return _alert_view(alert)


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=AlertView,
)
def acknowledge_alert(
    alert_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("alert.acknowledge")
    ),
    session: Session = Depends(get_db_session),
) -> AlertView:
    alert = AlertQueryService.get(
        session,
        alert_id,
    )
    _alert_scope(
        context,
        session,
        alert,
    )
    if alert.state == "RESOLVED":
        raise ApiError(
            status_code=409,
            code="alert_resolved",
            message="Resolved alert cannot be acknowledged.",
        )
    if alert.state == "ACKNOWLEDGED":
        return _alert_view(alert)

    before = {"state": alert.state}
    try:
        alert.state = "ACKNOWLEDGED"
        alert.acknowledged_at = utc_now()
        alert.acknowledged_by = context.user.id
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="alert.acknowledge",
            resource_type="alert",
            resource_id=alert.id,
            camera_id=alert.camera_id,
            before=before,
            after={"state": alert.state},
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _alert_view(alert)


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=AlertView,
)
def resolve_alert(
    alert_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("alert.manage")
    ),
    session: Session = Depends(get_db_session),
) -> AlertView:
    alert = AlertQueryService.get(
        session,
        alert_id,
    )
    _alert_scope(
        context,
        session,
        alert,
    )
    if alert.state == "RESOLVED":
        return _alert_view(alert)

    before = {"state": alert.state}
    try:
        alert.state = "RESOLVED"
        alert.resolved_at = utc_now()
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="alert.resolve",
            resource_type="alert",
            resource_id=alert.id,
            camera_id=alert.camera_id,
            before=before,
            after={"state": alert.state},
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _alert_view(alert)
