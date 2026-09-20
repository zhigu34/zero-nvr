from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import require_permission
from app.modules.auth.service import AuthContext

from .models import StorageTarget
from .schemas import (
    StorageTargetCreate,
    StorageTargetTestView,
    StorageTargetUpdate,
    StorageTargetView,
)
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
        exclude={"rclone_config"},
    )
    if "rclone_config" in body.model_fields_set:
        changes["rclone_config"] = (
            body.rclone_config.get_secret_value()
            if body.rclone_config is not None
            else None
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
    )
