from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ApiError
from app.integrations.ffmpeg import (
    FfmpegExportAdapter,
    FfmpegExportError,
    FfmpegInputClip,
)

from .models import ExportJob
from .plan import ExportPlanResolver


@dataclass(frozen=True, slots=True)
class ExportExecutionPlan:
    export_id: uuid.UUID
    output_path: Path
    clips: tuple[FfmpegInputClip, ...]
    requested_codec_mode: str
    selected_duration_ms: int
    has_gaps: bool


@dataclass(frozen=True, slots=True)
class ExportExecutionResult:
    export_id: uuid.UUID
    state: str
    rendered: bool


class ExportExecutionService:
    def __init__(
        self,
        settings: Settings,
        *,
        adapter_factory: Callable[..., FfmpegExportAdapter] = FfmpegExportAdapter,
    ) -> None:
        self.settings = settings
        self._adapter_factory = adapter_factory

    def prepare(
        self,
        database: Database,
        *,
        export_id: uuid.UUID,
    ) -> ExportExecutionPlan | ExportExecutionResult:
        now = datetime.now(UTC)
        with database.session() as session:
            job = session.get(ExportJob, export_id)
            if job is None:
                raise ApiError(
                    status_code=404,
                    code="export_not_found",
                    message="Export was not found.",
                )

            if job.state == "COMPLETED":
                session.commit()
                return ExportExecutionResult(
                    export_id=job.id,
                    state=job.state,
                    rendered=False,
                )
            if job.state in {"CANCELLED", "EXPIRED"}:
                session.commit()
                return ExportExecutionResult(
                    export_id=job.id,
                    state=job.state,
                    rendered=False,
                )
            if job.expires_at <= now:
                job.state = "EXPIRED"
                job.completed_at = now
                session.commit()
                return ExportExecutionResult(
                    export_id=job.id,
                    state="EXPIRED",
                    rendered=False,
                )

            try:
                plan = ExportPlanResolver.build(
                    session,
                    camera_id=job.camera_id,
                    start_at=job.requested_start_at,
                    end_at=job.requested_end_at,
                    gap_policy=job.gap_policy,
                )
            except ApiError as exc:
                job.state = "FAILED"
                job.error_code = exc.code
                job.completed_at = now
                session.commit()
                return ExportExecutionResult(
                    export_id=job.id,
                    state="FAILED",
                    rendered=False,
                )

            output_path = (
                self.settings.cache_dir
                / "exports"
                / f"{job.id}.mp4"
            ).resolve(strict=False)
            clips = tuple(
                FfmpegInputClip(
                    file_path=item.file_path,
                    inpoint_seconds=item.inpoint_seconds,
                    outpoint_seconds=item.outpoint_seconds,
                    codec=item.codec,
                )
                for item in plan.items
            )

            job.state = "RUNNING"
            job.started_at = now
            job.completed_at = None
            job.error_code = None
            job.output_path = str(output_path)
            job.selected_segment_count = len(clips)
            job.actual_duration_ms = plan.actual_duration_ms
            job.metadata_json = {
                "selected_duration_ms": plan.actual_duration_ms,
                "has_gaps": plan.has_gaps,
            }
            session.commit()

            return ExportExecutionPlan(
                export_id=job.id,
                output_path=output_path,
                clips=clips,
                requested_codec_mode=job.codec_mode,
                selected_duration_ms=plan.actual_duration_ms,
                has_gaps=plan.has_gaps,
            )

    @staticmethod
    def _mark_failed(
        database: Database,
        *,
        export_id: uuid.UUID,
        error_code: str,
    ) -> None:
        with database.session() as session:
            job = session.get(ExportJob, export_id)
            if job is None:
                return
            if job.state in {"CANCELLED", "EXPIRED"}:
                session.commit()
                return
            job.state = "FAILED"
            job.error_code = error_code
            job.completed_at = datetime.now(UTC)
            session.commit()

    @staticmethod
    def _complete(
        database: Database,
        *,
        export_id: uuid.UUID,
        output_path: Path,
        size_bytes: int,
        duration_ms: int,
        effective_codec_mode: str,
    ) -> ExportExecutionResult:
        with database.session() as session:
            job = session.get(ExportJob, export_id)
            if job is None:
                output_path.unlink(missing_ok=True)
                return ExportExecutionResult(
                    export_id=export_id,
                    state="CANCELLED",
                    rendered=False,
                )

            if job.state in {"CANCELLED", "EXPIRED"}:
                output_path.unlink(missing_ok=True)
                session.commit()
                return ExportExecutionResult(
                    export_id=job.id,
                    state=job.state,
                    rendered=False,
                )

            now = datetime.now(UTC)
            if job.expires_at <= now:
                output_path.unlink(missing_ok=True)
                job.state = "EXPIRED"
                job.output_path = None
                job.size_bytes = None
                job.completed_at = now
                session.commit()
                return ExportExecutionResult(
                    export_id=job.id,
                    state="EXPIRED",
                    rendered=False,
                )

            metadata = dict(job.metadata_json or {})
            metadata["effective_codec_mode"] = (
                effective_codec_mode
            )
            job.metadata_json = metadata
            job.state = "COMPLETED"
            job.output_path = str(output_path)
            job.size_bytes = size_bytes
            job.actual_duration_ms = duration_ms
            job.error_code = None
            job.completed_at = now
            session.commit()
            return ExportExecutionResult(
                export_id=job.id,
                state="COMPLETED",
                rendered=True,
            )

    def execute(
        self,
        database: Database,
        *,
        export_id: uuid.UUID,
    ) -> ExportExecutionResult:
        prepared = self.prepare(
            database,
            export_id=export_id,
        )
        if isinstance(
            prepared,
            ExportExecutionResult,
        ):
            return prepared

        adapter = self._adapter_factory(
            ffmpeg_binary=self.settings.ffmpeg_binary,
            ffprobe_binary=self.settings.ffprobe_binary,
            timeout_seconds=self.settings.ffmpeg_timeout_seconds,
        )
        try:
            result = adapter.render(
                clips=list(prepared.clips),
                output_path=prepared.output_path,
                codec_mode=prepared.requested_codec_mode,
            )
        except FfmpegExportError as exc:
            self._mark_failed(
                database,
                export_id=prepared.export_id,
                error_code=exc.code,
            )
            raise

        return self._complete(
            database,
            export_id=prepared.export_id,
            output_path=result.output_path,
            size_bytes=result.size_bytes,
            duration_ms=result.duration_ms,
            effective_codec_mode=result.codec_mode,
        )


class ExportCleanupService:
    @staticmethod
    def expire(
        database: Database,
        *,
        now: datetime | None = None,
    ) -> int:
        from sqlalchemy import select

        reference = now or datetime.now(UTC)
        paths: list[Path] = []
        count = 0
        with database.session() as session:
            jobs = list(
                session.scalars(
                    select(ExportJob).where(
                        ExportJob.expires_at <= reference,
                        ExportJob.state.notin_(
                            ["EXPIRED", "CANCELLED", "RUNNING"]
                        ),
                    )
                )
            )
            for job in jobs:
                if job.output_path:
                    paths.append(
                        Path(job.output_path)
                    )
                job.state = "EXPIRED"
                job.output_path = None
                job.size_bytes = None
                job.completed_at = reference
                count += 1
            session.commit()

        for path in paths:
            path.unlink(missing_ok=True)
        return count
