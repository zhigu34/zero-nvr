from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import require_permission
from app.modules.auth.service import AuthContext
from app.modules.recordings.models import RetentionPolicy

from .models import StorageTarget
from .schemas import (
    RetentionPolicyCreate,
    RetentionPolicyUpdate,
    RetentionPolicyView,
    StorageTargetCreate,
    StorageTargetRecordingSwitchRequest,
    StorageTargetRecordingSwitchView,
    StorageTargetTestView,
    StorageTargetUpdate,
    StorageTargetView,
)
from .retention_admin import RetentionPolicyAdminService
from .service import StorageTargetService


router = APIRouter()


def _view(target: StorageTarget) -> StorageTargetView:
    return StorageTargetView(
        id=target.id,
        type=target.type,
        role=target.role,
        name=target.name,
        enabled=target.enabled,
        config=target.config_json or {},
        credentials_configured=(
            target.credential_secret_ref is not None
        ),
    )


def _retention_view(
    policy: RetentionPolicy,
) -> RetentionPolicyView:
    return RetentionPolicyView(
        id=policy.id,
        name=policy.name,
        scope_type=policy.scope_type,
        scope_id=policy.scope_id,
        ordinary_keep_days=policy.ordinary_keep_days,
        event_keep_days=policy.event_keep_days,
        manual_keep_days=policy.manual_keep_days,
        mode=policy.mode,
        require_archive_before_delete=(
            policy.require_archive_before_delete
        ),
        enabled=policy.enabled,
    )


def _retention_audit_snapshot(
    policy: RetentionPolicy,
) -> dict[str, Any]:
    return {
        "name": policy.name,
        "scope_type": policy.scope_type,
        "scope_id": (
            str(policy.scope_id)
            if policy.scope_id is not None
            else None
        ),
        "ordinary_keep_days": policy.ordinary_keep_days,
        "event_keep_days": policy.event_keep_days,
        "manual_keep_days": policy.manual_keep_days,
        "mode": policy.mode,
        "require_archive_before_delete": (
            policy.require_archive_before_delete
        ),
        "enabled": policy.enabled,
    }


def _audit_snapshot(target: StorageTarget) -> dict[str, Any]:
    return {
        "type": target.type,
        "role": target.role,
        "name": target.name,
        "enabled": target.enabled,
        "config": target.config_json or {},
        "credentials_configured": (
            target.credential_secret_ref is not None
        ),
    }


@router.get(
    "/targets",
    response_model=list[StorageTargetView],
)
def list_storage_targets(
    _context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> list[StorageTargetView]:
    return [
        _view(item)
        for item in StorageTargetService.list(session)
    ]


@router.post(
    "/targets",
    response_model=StorageTargetView,
    status_code=201,
)
def create_storage_target(
    body: StorageTargetCreate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> StorageTargetView:
    service = StorageTargetService(
        request.app.state.settings
    )
    try:
        target = service.create(
            session,
            target_type=body.type,
            role=body.role,
            name=body.name,
            enabled=body.enabled,
            config=body.config,
            rclone_config=(
                body.rclone_config.get_secret_value()
                if body.rclone_config is not None
                else None
            ),
            openlist_webdav=(
                {
                    "url": body.openlist_webdav.url,
                    "username": (
                        body.openlist_webdav.username
                    ),
                    "password": (
                        body.openlist_webdav.password
                        .get_secret_value()
                    ),
                }
                if body.openlist_webdav
                is not None
                else None
            ),
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="storage_target.create",
            resource_type="storage_target",
            resource_id=target.id,
            after=_audit_snapshot(target),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _view(target)


@router.get(
    "/targets/{target_id}",
    response_model=StorageTargetView,
)
def get_storage_target(
    target_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> StorageTargetView:
    return _view(
        StorageTargetService.get(
            session,
            target_id,
        )
    )


@router.patch(
    "/targets/{target_id}",
    response_model=StorageTargetView,
)
def update_storage_target(
    target_id: uuid.UUID,
    body: StorageTargetUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> StorageTargetView:
    service = StorageTargetService(
        request.app.state.settings
    )
    target = service.get(session, target_id)
    before = _audit_snapshot(target)

    changes = body.model_dump(
        exclude_unset=True,
        exclude={
            "rclone_config",
            "openlist_webdav",
        },
    )
    credential_action = (
        body.rclone_config_action
    )
    has_raw_config = (
        body.rclone_config is not None
    )
    has_openlist_config = (
        body.openlist_webdav is not None
    )
    if (
        has_raw_config
        and has_openlist_config
    ):
        raise ApiError(
            status_code=400,
            code="rclone_config_conflict",
            message=(
                "Provide either raw rclone configuration "
                "or OpenList WebDAV credentials, not both."
            ),
        )
    has_credential_value = (
        has_raw_config
        or has_openlist_config
    )
    if (
        credential_action == "replace"
        and not has_credential_value
    ):
        raise ApiError(
            status_code=400,
            code="rclone_config_update_invalid",
            message=(
                "rclone credential replacement "
                "requires a new value."
            ),
        )
    if (
        credential_action != "replace"
        and has_credential_value
    ):
        raise ApiError(
            status_code=400,
            code="rclone_config_update_invalid",
            message=(
                "rclone credential value is only "
                "accepted with action=replace."
            ),
        )
    changes["rclone_config_action"] = (
        credential_action
    )
    if has_raw_config:
        assert body.rclone_config is not None
        changes["rclone_config"] = (
            body.rclone_config.get_secret_value()
        )
    if has_openlist_config:
        assert body.openlist_webdav is not None
        changes["openlist_webdav"] = {
            "url": body.openlist_webdav.url,
            "username": (
                body.openlist_webdav.username
            ),
            "password": (
                body.openlist_webdav.password
                .get_secret_value()
            ),
        }

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
            action="storage_target.update",
            resource_type="storage_target",
            resource_id=target.id,
            before=before,
            after=_audit_snapshot(target),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _view(target)


@router.post(
    "/targets/{source_target_id}/switch-recording",
    response_model=StorageTargetRecordingSwitchView,
)
def switch_recording_target(
    source_target_id: uuid.UUID,
    body: StorageTargetRecordingSwitchRequest,
    request: Request,
    context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> StorageTargetRecordingSwitchView:
    service = StorageTargetService(
        request.app.state.settings
    )
    source = service.get(
        session,
        source_target_id,
    )
    destination = service.get(
        session,
        body.destination_target_id,
    )
    before_source = _audit_snapshot(source)
    before_destination = _audit_snapshot(
        destination
    )

    try:
        result = service.switch_recording_target(
            session,
            source=source,
            destination=destination,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action=(
                "storage_target."
                "recording_route_switch"
            ),
            resource_type="storage_target",
            resource_id=source.id,
            before={
                "source": before_source,
                "destination": (
                    before_destination
                ),
            },
            after={
                "source": _audit_snapshot(source),
                "destination": (
                    _audit_snapshot(destination)
                ),
                "explicit_policies_updated": (
                    result.explicit_policies_updated
                ),
                "implicit_policies_rebound": (
                    result.implicit_policies_rebound
                ),
                "default_moved": (
                    result.default_moved
                ),
                "affected_camera_ids": [
                    str(item)
                    for item in (
                        result.affected_camera_ids
                    )
                ],
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    failed_camera_ids: list[str] = []
    for camera_id in result.affected_camera_ids:
        try:
            request.app.state.recording_tasks.reconcile_runtime(
                camera_id,
                force_reconfigure=True,
            )
        except Exception:
            failed_camera_ids.append(
                str(camera_id)
            )

    if failed_camera_ids:
        raise ApiError(
            status_code=503,
            code=(
                "recording_target_switch_"
                "reconcile_failed"
            ),
            message=(
                "Recording target routing was saved, "
                "but one or more camera runtimes "
                "could not be queued for reconfiguration."
            ),
            details={
                "routing_persisted": True,
                "failed_camera_ids": (
                    failed_camera_ids
                ),
            },
        )

    return StorageTargetRecordingSwitchView(
        source_target_id=(
            result.source_target_id
        ),
        destination_target_id=(
            result.destination_target_id
        ),
        explicit_policies_updated=(
            result.explicit_policies_updated
        ),
        implicit_policies_rebound=(
            result.implicit_policies_rebound
        ),
        default_moved=result.default_moved,
        affected_camera_ids=list(
            result.affected_camera_ids
        ),
    )


@router.delete(
    "/targets/{target_id}",
    status_code=204,
)
def delete_storage_target(
    target_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    service = StorageTargetService(
        request.app.state.settings
    )
    target = service.get(session, target_id)
    before = _audit_snapshot(target)
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
            action="storage_target.delete",
            resource_type="storage_target",
            resource_id=resource_id,
            before=before,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return Response(status_code=204)


@router.post(
    "/targets/{target_id}/test",
    response_model=StorageTargetTestView,
)
def test_storage_target(
    target_id: uuid.UUID,
    request: Request,
    _context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> StorageTargetTestView:
    service = StorageTargetService(
        request.app.state.settings
    )
    target = service.get(session, target_id)
    target_type = target.type
    config = dict(target.config_json or {})
    rclone_config: str | None = None

    if target_type == "rclone":
        resolved = service.resolve_rclone(
            session,
            target=target,
        )
        rclone_config = resolved.config_text

    # Never keep the SQLite read transaction open while filesystem/rclone IO
    # runs.
    session.commit()

    result = service.test_target(
        target_type=target_type,
        config=config,
        rclone_config=rclone_config,
    )
    return StorageTargetTestView(
        type=result.type,
        detail=result.detail,
        free_bytes=result.free_bytes,
        total_bytes=result.total_bytes,
        used_bytes=result.used_bytes,
        used_percent=result.used_percent,
        capacity_level=result.capacity_level,
        warning_percent=result.warning_percent,
        high_percent=result.high_percent,
        critical_percent=result.critical_percent,
    )



@router.get(
    "/retention-policies",
    response_model=list[RetentionPolicyView],
)
def list_retention_policies(
    _context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> list[RetentionPolicyView]:
    return [
        _retention_view(item)
        for item in RetentionPolicyAdminService.list(session)
    ]


@router.post(
    "/retention-policies",
    response_model=RetentionPolicyView,
    status_code=201,
)
def create_retention_policy(
    body: RetentionPolicyCreate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> RetentionPolicyView:
    try:
        policy = RetentionPolicyAdminService.create(
            session,
            name=body.name,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            ordinary_keep_days=body.ordinary_keep_days,
            event_keep_days=body.event_keep_days,
            manual_keep_days=body.manual_keep_days,
            mode=body.mode,
            require_archive_before_delete=(
                body.require_archive_before_delete
            ),
            enabled=body.enabled,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="retention_policy.create",
            resource_type="retention_policy",
            resource_id=policy.id,
            after=_retention_audit_snapshot(policy),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _retention_view(policy)


@router.get(
    "/retention-policies/{policy_id}",
    response_model=RetentionPolicyView,
)
def get_retention_policy(
    policy_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> RetentionPolicyView:
    return _retention_view(
        RetentionPolicyAdminService.get(
            session,
            policy_id,
        )
    )


@router.patch(
    "/retention-policies/{policy_id}",
    response_model=RetentionPolicyView,
)
def update_retention_policy(
    policy_id: uuid.UUID,
    body: RetentionPolicyUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> RetentionPolicyView:
    policy = RetentionPolicyAdminService.get(
        session,
        policy_id,
    )
    before = _retention_audit_snapshot(policy)
    changes = body.model_dump(exclude_unset=True)

    try:
        policy = RetentionPolicyAdminService.update(
            session,
            policy=policy,
            changes=changes,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="retention_policy.update",
            resource_type="retention_policy",
            resource_id=policy.id,
            before=before,
            after=_retention_audit_snapshot(policy),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _retention_view(policy)


@router.delete(
    "/retention-policies/{policy_id}",
    status_code=204,
)
def delete_retention_policy(
    policy_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("storage.manage")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    policy = RetentionPolicyAdminService.get(
        session,
        policy_id,
    )
    before = _retention_audit_snapshot(policy)
    resource_id = policy.id

    try:
        RetentionPolicyAdminService.delete(
            session,
            policy=policy,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="retention_policy.delete",
            resource_type="retention_policy",
            resource_id=resource_id,
            before=before,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return Response(status_code=204)
