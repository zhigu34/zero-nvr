from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError

from .models import ExportJob


class ExportService:
    default_ttl = timedelta(hours=24)
    max_range = timedelta(days=7)

    @staticmethod
    def get(
        session: Session,
        export_id: uuid.UUID,
    ) -> ExportJob:
        job = session.get(ExportJob, export_id)
        if job is None:
            raise ApiError(
                status_code=404,
                code="export_not_found",
                message="Export was not found.",
            )
        return job

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        requested_by: uuid.UUID,
        start_at: datetime,
        end_at: datetime,
        format: str,
        codec_mode: str,
        gap_policy: str,
        idempotency_key: str | None,
    ) -> tuple[ExportJob, bool]:
        if end_at <= start_at:
            raise ApiError(
                status_code=400,
                code="invalid_time_range",
                message="Export range end must be after range start.",
            )
        if end_at - start_at > cls.max_range:
            raise ApiError(
                status_code=400,
                code="export_range_too_large",
                message="Export range may not exceed 7 days.",
            )

        key_hash: str | None = None
        if idempotency_key is not None:
            normalized = idempotency_key.strip()
            if not normalized or len(normalized) > 256:
                raise ApiError(
                    status_code=400,
                    code="idempotency_key_invalid",
                    message="Idempotency-Key must be 1 to 256 characters.",
                )
            key_hash = hashlib.sha256(
                f"{requested_by}:{normalized}".encode(
                    "utf-8"
                )
            ).hexdigest()
            existing = session.scalar(
                select(ExportJob).where(
                    ExportJob.idempotency_key_hash
                    == key_hash
                )
            )
            if existing is not None:
                return existing, False

        now = datetime.now(UTC)
        duration_ms = int(
            round(
                (end_at - start_at).total_seconds()
                * 1000
            )
        )
        job = ExportJob(
            camera_id=camera_id,
            requested_by=requested_by,
            requested_start_at=start_at,
            requested_end_at=end_at,
            requested_duration_ms=duration_ms,
            idempotency_key_hash=key_hash,
            format=format,
            codec_mode=codec_mode,
            gap_policy=gap_policy,
            state="PENDING",
            expires_at=now + cls.default_ttl,
            metadata_json={},
        )
        session.add(job)
        try:
            session.flush()
        except IntegrityError:
            if key_hash is None:
                raise
            session.rollback()
            existing = session.scalar(
                select(ExportJob).where(
                    ExportJob.idempotency_key_hash
                    == key_hash
                )
            )
            if existing is None:
                raise
            return existing, False
        return job, True

    @staticmethod
    def cancel(
        session: Session,
        *,
        job: ExportJob,
    ) -> Path | None:
        if job.state in {
            "CANCELLED",
            "EXPIRED",
        }:
            return (
                Path(job.output_path)
                if job.output_path
                else None
            )
        job.state = "CANCELLED"
        job.completed_at = datetime.now(UTC)
        output = (
            Path(job.output_path)
            if job.output_path
            else None
        )
        job.output_path = None
        job.size_bytes = None
        session.flush()
        return output
