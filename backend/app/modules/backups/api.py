from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import require_permission
from app.modules.auth.service import AuthContext

from .execution import BackupRunService
from .models import BackupPolicy, BackupSet
from .query import BackupQueryService
from .schemas import (
    BackupPolicyCreate,
    BackupPolicyUpdate,
    BackupPolicyView,
    BackupRunRequest,
    BackupSetPage,
    BackupSetView,
)
from .service import BackupPolicyService


router = APIRouter()


def _policy_view(
    policy: BackupPolicy,
) -> BackupPolicyView:
    return BackupPolicyView(
        id=policy.id,
        name=policy.name,
        enabled=policy.enabled,
        database_backend=policy.database_backend,
        schedule=policy.schedule_json or {},
        retention=policy.retention_policy_json or {},
        verify_after_backup=policy.verify_after_backup,
        repository_check_schedule=(
            policy.repository_check_schedule_json or {}
        ),
        include_deployment_config=(
            policy.include_deployment_config
        ),
        repository_configured=(
            policy.repository_config_ref is not None
        ),
        credentials_configured=(
            policy.credential_secret_ref is not None
        ),
    )


def _set_view(item: BackupSet) -> BackupSetView:
    return BackupSetView(
        id=item.id,
        backup_policy_id=item.backup_policy_id,
        state=item.state,
        reason=item.reason,
        started_at=item.started_at,
        completed_at=item.completed_at,
        app_version=item.app_version,
        schema_revision=item.schema_revision,
        database_engine=item.database_engine,
        restic_snapshot_id=item.restic_snapshot_id,
        size_bytes=item.size_bytes,
        verification_state=item.verification_state,
        last_verified_at=item.last_verified_at,
        error_code=item.error_code,
        sanitized_error=item.sanitized_error,
        created_at=item.created_at,
    )


def _policy_snapshot(
    policy: BackupPolicy,
) -> dict[str, Any]:
    return {
        "name": policy.name,
        "enabled": policy.enabled,
        "database_backend": policy.database_backend,
        "schedule": policy.schedule_json or {},
        "retention": policy.retention_policy_json or {},
        "verify_after_backup": policy.verify_after_backup,
        "repository_check_schedule": (
            policy.repository_check_schedule_json or {}
        ),
        "include_deployment_config": (
            policy.include_deployment_config
        ),
        "repository_configured": True,
        "credentials_configured": (
            policy.credential_secret_ref is not None
        ),
    }


def _environment(
    body,
) -> dict[str, str]:
    return {
        key: value.get_secret_value()
        for key, value in body.environment.items()
    }


@router.get(
    "/policies",
    response_model=list[BackupPolicyView],
)
def list_backup_policies(
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
    session: Session = Depends(get_db_session),
) -> list[BackupPolicyView]:
    return [
        _policy_view(item)
        for item in BackupPolicyService.list(session)
    ]


@router.post(
    "/policies",
    response_model=BackupPolicyView,
    status_code=201,
)
def create_backup_policy(
    body: BackupPolicyCreate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("system.manage")
    ),
    session: Session = Depends(get_db_session),
) -> BackupPolicyView:
    active_backend = (
        request.app.state.database.url.get_backend_name()
    )
    if body.database_backend != active_backend:
        raise ApiError(
            status_code=400,
            code="backup_database_backend_mismatch",
            message="Backup policy database backend must match the active database.",
        )

    service = BackupPolicyService(
        request.app.state.settings
    )
    try:
        policy = service.create(
            session,
            name=body.name,
            enabled=body.enabled,
            repository=body.repository.get_secret_value(),
            password=body.credentials.password.get_secret_value(),
            environment=_environment(body.credentials),
            initialize_if_missing=body.initialize_if_missing,
            database_backend=body.database_backend,
            schedule=body.schedule,
            retention=body.retention,
            verify_after_backup=body.verify_after_backup,
            repository_check_schedule=(
                body.repository_check_schedule
            ),
            include_deployment_config=(
                body.include_deployment_config
            ),
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="backup_policy.create",
            resource_type="backup_policy",
            resource_id=policy.id,
            after=_policy_snapshot(policy),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _policy_view(policy)


@router.get(
    "/policies/{policy_id}",
    response_model=BackupPolicyView,
)
def get_backup_policy(
    policy_id: uuid.UUID,
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
    session: Session = Depends(get_db_session),
) -> BackupPolicyView:
    return _policy_view(
        BackupPolicyService.get(
            session,
            policy_id,
        )
    )


@router.patch(
    "/policies/{policy_id}",
    response_model=BackupPolicyView,
)
def update_backup_policy(
    policy_id: uuid.UUID,
    body: BackupPolicyUpdate,
    request: Request,
    context: AuthContext = Depends(
        require_permission("system.manage")
    ),
    session: Session = Depends(get_db_session),
) -> BackupPolicyView:
    service = BackupPolicyService(
        request.app.state.settings
    )
    policy = service.get(
        session,
        policy_id,
    )
    before = _policy_snapshot(policy)
    changes: dict[str, object] = body.model_dump(
        exclude_unset=True,
        exclude={"repository", "credentials"},
    )
    if "repository" in body.model_fields_set:
        if body.repository is None:
            raise ApiError(
                status_code=400,
                code="backup_repository_invalid",
                message="Backup repository cannot be cleared.",
            )
        changes["repository"] = (
            body.repository.get_secret_value()
        )
    if "credentials" in body.model_fields_set:
        if body.credentials is None:
            raise ApiError(
                status_code=400,
                code="backup_credentials_invalid",
                message="Backup credentials cannot be cleared.",
            )
        changes["credentials"] = {
            "password": (
                body.credentials.password.get_secret_value()
            ),
            "environment": _environment(
                body.credentials
            ),
        }

    try:
        policy = service.update(
            session,
            policy=policy,
            changes=changes,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="backup_policy.update",
            resource_type="backup_policy",
            resource_id=policy.id,
            before=before,
            after=_policy_snapshot(policy),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _policy_view(policy)


@router.get(
    "",
    response_model=BackupSetPage,
)
def list_backups(
    policy_id: uuid.UUID | None = None,
    state: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    _context: AuthContext = Depends(
        require_permission("system.view")
    ),
    session: Session = Depends(get_db_session),
) -> BackupSetPage:
    page = BackupQueryService.list(
        session,
        policy_id=policy_id,
        state=state,
        cursor=cursor,
        limit=limit,
    )
    return BackupSetPage(
        items=[
            _set_view(item)
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/run",
    response_model=BackupSetView,
    status_code=202,
)
def run_backup(
    body: BackupRunRequest,
    request: Request,
    context: AuthContext = Depends(
        require_permission("system.manage")
    ),
    session: Session = Depends(get_db_session),
) -> BackupSetView:
    policy = BackupPolicyService.get(
        session,
        body.policy_id,
    )
    reason = body.reason.strip() or "manual"
    try:
        backup_set, created = BackupRunService.reserve(
            session,
            policy=policy,
            settings=request.app.state.settings,
            database=request.app.state.database,
            reason=reason,
        )
        if created:
            append_audit_event(
                session,
                request=request,
                actor_id=context.user.id,
                action="backup.run",
                resource_type="backup_set",
                resource_id=backup_set.id,
                after={
                    "policy_id": str(policy.id),
                    "reason": reason,
                },
            )
        session.commit()
    except Exception:
        session.rollback()
        raise

    if created:
        try:
            request.app.state.backup_tasks.run(
                backup_set.id
            )
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="backup_task_queue_unavailable",
                message="Backup run was saved but could not be queued.",
                details={
                    "backup_persisted": True,
                    "backup_id": str(backup_set.id),
                },
            ) from exc

    return _set_view(backup_set)


@router.post(
    "/{backup_id}/verify",
    response_model=BackupSetView,
    status_code=202,
)
def verify_backup(
    backup_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("system.manage")
    ),
    session: Session = Depends(get_db_session),
) -> BackupSetView:
    item = session.get(BackupSet, backup_id)
    if item is None:
        raise ApiError(
            status_code=404,
            code="backup_not_found",
            message="Backup set was not found.",
        )
    if (
        item.state != "COMPLETED"
        or item.restic_snapshot_id is None
    ):
        raise ApiError(
            status_code=409,
            code="backup_not_verifiable",
            message="Backup set cannot be verified.",
        )

    previous_verification_state = item.verification_state
    try:
        item.verification_state = "PENDING"
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="backup.verify",
            resource_type="backup_set",
            resource_id=item.id,
            before={
                "verification_state": previous_verification_state
            },
            after={
                "verification_state": "PENDING",
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    try:
        request.app.state.backup_tasks.verify(
            item.id
        )
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="backup_task_queue_unavailable",
            message="Backup verification request was saved but could not be queued.",
            details={
                "backup_persisted": True,
                "backup_id": str(item.id),
            },
        ) from exc
    return _set_view(item)
