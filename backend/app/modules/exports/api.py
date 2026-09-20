from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
    Request,
    Response,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.modules.audit.service import append_audit_event
from app.modules.auth.dependencies import (
    get_effective_camera_scope,
    require_permission,
)
from app.modules.auth.service import AuthContext
from app.modules.cameras.service import CameraService

from .models import ExportJob
from .query import ExportQueryService
from .schemas import ExportCreate, ExportPage, ExportView
from .service import ExportService


router = APIRouter()


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError(
            status_code=422,
            code="timezone_required",
            message=f"{field} must include a timezone offset.",
        )
    return value.astimezone(UTC)


def _view(job: ExportJob) -> ExportView:
    return ExportView(
        id=job.id,
        camera_id=job.camera_id,
        requested_by=job.requested_by,
        start_at=job.requested_start_at,
        end_at=job.requested_end_at,
        requested_duration_ms=job.requested_duration_ms,
        format=job.format,
        codec_mode=job.codec_mode,
        gap_policy=job.gap_policy,
        state=job.state,
        size_bytes=job.size_bytes,
        actual_duration_ms=job.actual_duration_ms,
        selected_segment_count=job.selected_segment_count,
        metadata=job.metadata_json or {},
        error_code=job.error_code,
        expires_at=job.expires_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


def _audit_snapshot(job: ExportJob) -> dict[str, object]:
    return {
        "camera_id": str(job.camera_id),
        "start_at": job.requested_start_at.isoformat(),
        "end_at": job.requested_end_at.isoformat(),
        "format": job.format,
        "codec_mode": job.codec_mode,
        "gap_policy": job.gap_policy,
        "state": job.state,
    }


def _scoped_export(
    session: Session,
    *,
    context: AuthContext,
    export_id: uuid.UUID,
) -> ExportJob:
    job = ExportService.get(session, export_id)
    scope = get_effective_camera_scope(
        context,
        session,
    )
    if not scope.allows(job.camera_id):
        raise ApiError(
            status_code=404,
            code="export_not_found",
            message="Export was not found.",
        )
    return job


def _safe_output_path(
    request: Request,
    raw_path: str | None,
) -> Path | None:
    if not raw_path:
        return None
    root = (
        request.app.state.settings.cache_dir
        / "exports"
    ).resolve(strict=False)
    path = Path(raw_path).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


@router.post(
    "/exports",
    response_model=ExportView,
    status_code=201,
)
def create_export(
    body: ExportCreate,
    request: Request,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    context: AuthContext = Depends(
        require_permission("recording.export")
    ),
    session: Session = Depends(get_db_session),
) -> ExportView:
    scope = get_effective_camera_scope(
        context,
        session,
    )
    if not scope.allows(body.camera_id):
        raise ApiError(
            status_code=404,
            code="camera_not_found",
            message="Camera was not found.",
        )
    CameraService.get_camera(
        session,
        body.camera_id,
    )

    start_at = _utc(body.start_at, field="start_at")
    end_at = _utc(body.end_at, field="end_at")

    try:
        job, created = ExportService.create(
            session,
            camera_id=body.camera_id,
            requested_by=context.user.id,
            start_at=start_at,
            end_at=end_at,
            format=body.format,
            codec_mode=body.codec_mode,
            gap_policy=body.gap_policy,
            idempotency_key=idempotency_key,
        )
        if created:
            append_audit_event(
                session,
                request=request,
                actor_id=context.user.id,
                action="export.create",
                resource_type="export",
                resource_id=job.id,
                camera_id=job.camera_id,
                after=_audit_snapshot(job),
            )
        session.commit()
    except Exception:
        session.rollback()
        raise

    if created:
        try:
            request.app.state.export_tasks.render(
                job.id
            )
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="export_task_queue_unavailable",
                message="Export was saved but background processing could not be queued.",
                details={
                    "export_persisted": True,
                    "export_id": str(job.id),
                },
            ) from exc

    return _view(job)


@router.get(
    "/exports",
    response_model=ExportPage,
)
def list_exports(
    state: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    context: AuthContext = Depends(
        require_permission("recording.export")
    ),
    session: Session = Depends(get_db_session),
) -> ExportPage:
    scope = get_effective_camera_scope(
        context,
        session,
    )
    page = ExportQueryService.list(
        session,
        allowed_camera_ids=(
            None if scope.all_cameras
            else scope.camera_ids
        ),
        state=state,
        cursor=cursor,
        limit=limit,
    )
    return ExportPage(
        items=[_view(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/exports/{export_id}",
    response_model=ExportView,
)
def get_export(
    export_id: uuid.UUID,
    context: AuthContext = Depends(
        require_permission("recording.export")
    ),
    session: Session = Depends(get_db_session),
) -> ExportView:
    return _view(
        _scoped_export(
            session,
            context=context,
            export_id=export_id,
        )
    )


@router.delete(
    "/exports/{export_id}",
    status_code=204,
)
def delete_export(
    export_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("recording.export")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    job = _scoped_export(
        session,
        context=context,
        export_id=export_id,
    )
    before = _audit_snapshot(job)
    try:
        output = ExportService.cancel(
            session,
            job=job,
        )
        append_audit_event(
            session,
            request=request,
            actor_id=context.user.id,
            action="export.cancel",
            resource_type="export",
            resource_id=job.id,
            camera_id=job.camera_id,
            before=before,
            after=_audit_snapshot(job),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    safe_output = _safe_output_path(
        request,
        str(output) if output is not None else None,
    )
    if safe_output is not None:
        safe_output.unlink(missing_ok=True)
    return Response(status_code=204)


@router.get(
    "/exports/{export_id}/download",
)
def download_export(
    export_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(
        require_permission("recording.export")
    ),
    session: Session = Depends(get_db_session),
):
    job = _scoped_export(
        session,
        context=context,
        export_id=export_id,
    )
    if job.expires_at <= datetime.now(UTC):
        raise ApiError(
            status_code=410,
            code="export_expired",
            message="Export has expired.",
        )
    if job.state != "COMPLETED":
        raise ApiError(
            status_code=409,
            code="export_not_ready",
            message="Export is not ready for download.",
            details={"state": job.state},
        )

    path = _safe_output_path(
        request,
        job.output_path,
    )
    if path is None or not path.is_file():
        raise ApiError(
            status_code=409,
            code="export_output_missing",
            message="Export output is unavailable.",
        )

    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"zero-nvr-export-{job.id}.mp4",
    )
