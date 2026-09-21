from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.cameras.models import CameraStreamProfile
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
    RecordingTrigger,
)
from app.modules.storage.models import RecordingLocation
from app.modules.storage.recording_resolver import RecordingStorageResolver


@dataclass(frozen=True, slots=True)
class FinalizedRecordingEvidence:
    vhost: str
    app: str
    stream: str
    start_time_epoch: float
    duration_seconds: float
    file_size: int
    file_path: str


@dataclass(frozen=True, slots=True)
class CatalogIngestResult:
    segment: RecordingSegment | None
    created: bool
    ignored: bool = False
    ignore_reason: str | None = None


class RecordingCatalogService:
    """Canonical finalized-recording ingestion.

    Continuity proof is deliberately supplied as an in-memory previous segment
    id. No continuity/session runtime identity is persisted in the catalog.
    """

    expected_app = "zero-nvr"
    stream_prefix = "profile-"

    @classmethod
    def profile_id_from_stream(cls, stream: str) -> uuid.UUID:
        if not stream.startswith(cls.stream_prefix):
            raise ApiError(
                status_code=422,
                code="recording_stream_unrecognized",
                message="Recording stream identity is not managed by zero-nvr.",
            )
        raw = stream[len(cls.stream_prefix):]
        try:
            return uuid.UUID(hex=raw)
        except ValueError as exc:
            raise ApiError(
                status_code=422,
                code="recording_stream_unrecognized",
                message="Recording stream identity is invalid.",
            ) from exc

    @staticmethod
    def recording_reasons(
        session: Session,
        *,
        camera_id: uuid.UUID,
        started_at: datetime,
        ended_at: datetime,
    ) -> list[str]:
        reasons: set[str] = set()

        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )
        if (
            policy is not None
            and policy.enabled
            and policy.baseline_mode == "continuous"
        ):
            reasons.add("continuous")

        overlapping_trigger = session.scalar(
            select(RecordingTrigger.id)
            .where(
                RecordingTrigger.camera_id == camera_id,
                RecordingTrigger.state.notin_(["CANCELLED", "FAILED"]),
                RecordingTrigger.planned_start_at < ended_at,
                or_(
                    RecordingTrigger.planned_end_at.is_(None),
                    RecordingTrigger.planned_end_at > started_at,
                ),
            )
            .limit(1)
        )
        if overlapping_trigger is not None:
            reasons.add("event")

        return sorted(reasons)

    @staticmethod
    def _finalize_previous_from_boundary(
        session: Session,
        *,
        profile_id: uuid.UUID,
        previous_segment_id: uuid.UUID,
        boundary_at: datetime,
    ) -> RecordingSegment | None:
        previous = session.get(RecordingSegment, previous_segment_id)
        if previous is None:
            return None
        if previous.stream_profile_id != profile_id:
            return None
        if previous.timing_status != "PROVISIONAL":
            return None
        if boundary_at <= previous.started_at:
            return None

        normalized_started = boundary_at - timedelta(
            milliseconds=previous.duration_ms
        )
        if normalized_started >= boundary_at:
            return None

        previous.started_at = normalized_started
        previous.ended_at = boundary_at
        previous.timing_status = "FINAL"
        previous.timing_source = "NEXT_SEGMENT_BOUNDARY"
        session.flush()
        return previous

    @staticmethod
    def finalize_provisional_segment(
        session: Session,
        *,
        segment_id: uuid.UUID,
        boundary_at: datetime,
        timing_source: str = "EXPLICIT_STOP",
    ) -> RecordingSegment | None:
        segment = session.get(RecordingSegment, segment_id)
        if segment is None or segment.timing_status != "PROVISIONAL":
            return None
        if boundary_at <= segment.started_at:
            return None

        normalized_started = boundary_at - timedelta(
            milliseconds=segment.duration_ms
        )
        if normalized_started >= boundary_at:
            return None

        segment.started_at = normalized_started
        segment.ended_at = boundary_at
        segment.timing_status = "FINAL"
        segment.timing_source = timing_source
        session.flush()
        return segment

    @staticmethod
    def mark_source_loss_tail(
        session: Session,
        *,
        previous_segment_id: uuid.UUID | None,
        segment_id: uuid.UUID,
    ) -> None:
        """Move source-loss completion evidence to the latest known tail.

        Closed-generation hooks can arrive after reconnect and may arrive out
        of order. The continuity tracker decides whether *segment_id* is newer
        than the previously remembered segment. Once it is, completion reason
        follows that newest finalized media file without changing its timing
        projection or stretching coverage to the later unregister timestamp.
        """

        current = session.get(
            RecordingSegment,
            segment_id,
        )
        if current is None:
            return

        if (
            previous_segment_id is not None
            and previous_segment_id
            != segment_id
        ):
            previous = session.get(
                RecordingSegment,
                previous_segment_id,
            )
            if (
                previous is not None
                and (
                    previous.completion_reason
                    or ""
                ).lower()
                == "source_lost"
            ):
                previous.completion_reason = "NORMAL"

        current.completion_reason = "source_lost"
        session.flush()

    @classmethod
    def ingest_finalized(
        cls,
        session: Session,
        *,
        evidence: FinalizedRecordingEvidence,
        previous_segment_id: uuid.UUID | None = None,
    ) -> CatalogIngestResult:
        if evidence.app != cls.expected_app:
            return CatalogIngestResult(
                segment=None,
                created=False,
                ignored=True,
                ignore_reason="unmanaged_app",
            )
        if evidence.duration_seconds <= 0:
            raise ApiError(
                status_code=422,
                code="recording_duration_invalid",
                message="Finalized recording duration must be positive.",
            )
        if evidence.file_size < 0:
            raise ApiError(
                status_code=422,
                code="recording_file_size_invalid",
                message="Finalized recording file size is invalid.",
            )

        profile_id = cls.profile_id_from_stream(evidence.stream)
        profile = session.get(CameraStreamProfile, profile_id)
        if profile is None:
            raise ApiError(
                status_code=422,
                code="recording_stream_unknown",
                message="Recording stream profile does not exist.",
            )

        target = RecordingStorageResolver.local_target_for_camera(
            session,
            camera_id=profile.camera_id,
        )

        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == profile.camera_id
            )
        )

        try:
            object_path = RecordingStorageResolver.relative_object_path(
                target_root=target.root,
                file_path=evidence.file_path,
            )
        except ApiError as exc:
            # EVENT_ONLY rolling tmpfs fragments are intentionally ephemeral and
            # do not become canonical segments until promoted to local storage.
            if (
                exc.code == "recording_file_outside_target"
                and policy is not None
                and policy.enabled
                and policy.baseline_mode == "disabled"
                and policy.event_recording_enabled
            ):
                return CatalogIngestResult(
                    segment=None,
                    created=False,
                    ignored=True,
                    ignore_reason="event_only_ephemeral",
                )
            raise

        existing_location = session.scalar(
            select(RecordingLocation).where(
                RecordingLocation.storage_target_id == target.target.id,
                RecordingLocation.object_path == object_path,
            )
        )
        if existing_location is not None:
            existing = session.get(
                RecordingSegment,
                existing_location.recording_segment_id,
            )
            if existing is None:
                raise ApiError(
                    status_code=409,
                    code="recording_catalog_inconsistent",
                    message="Recording location references a missing segment.",
                )
            if (
                existing_location.size_bytes != evidence.file_size
                or existing.size_bytes != evidence.file_size
            ):
                raise ApiError(
                    status_code=409,
                    code="recording_location_conflict",
                    message="Recording path already exists with different media facts.",
                )
            return CatalogIngestResult(
                segment=existing,
                created=False,
            )

        raw_started = datetime.fromtimestamp(
            evidence.start_time_epoch,
            tz=UTC,
        )
        duration_ms = max(
            1,
            int(round(evidence.duration_seconds * 1000)),
        )
        raw_ended = raw_started + timedelta(milliseconds=duration_ms)

        if previous_segment_id is not None:
            cls._finalize_previous_from_boundary(
                session,
                profile_id=profile.id,
                previous_segment_id=previous_segment_id,
                boundary_at=raw_started,
            )

        reasons = cls.recording_reasons(
            session,
            camera_id=profile.camera_id,
            started_at=raw_started,
            ended_at=raw_ended,
        )

        segment = RecordingSegment(
            camera_id=profile.camera_id,
            stream_profile_id=profile.id,
            started_at=raw_started,
            ended_at=raw_ended,
            duration_ms=duration_ms,
            timing_status="PROVISIONAL",
            timing_source="HOOK_RAW",
            recording_reasons_json=reasons,
            size_bytes=evidence.file_size,
            codec=profile.codec,
            container="fmp4",
            source_media_server_id="default",
            source_app=evidence.app,
            source_stream=evidence.stream,
            integrity_status="UNKNOWN",
            completion_reason="NORMAL",
        )
        session.add(segment)
        session.flush()

        segment.locations.append(
            RecordingLocation(
                recording_segment_id=segment.id,
                storage_target_id=target.target.id,
                object_path=object_path,
                state="AVAILABLE",
                size_bytes=evidence.file_size,
            )
        )
        session.flush()

        return CatalogIngestResult(
            segment=segment,
            created=True,
        )
