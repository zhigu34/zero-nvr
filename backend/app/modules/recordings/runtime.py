from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.integrations.zlm import ZlmAdapter
from app.modules.cameras.media_runtime import CameraMediaRuntimeService
from app.modules.cameras.models import Camera, CameraStreamBinding, CameraStreamProfile
from app.modules.storage.recording_resolver import RecordingStorageResolver

from .catalog import RecordingCatalogService
from .models import RecordingPolicy


@dataclass(frozen=True, slots=True)
class DesiredRecorder:
    camera_id: uuid.UUID
    profile_id: uuid.UUID
    app: str
    stream: str
    target_root: str
    segment_target_seconds: int
    should_record: bool
    event_prebuffer_required: bool


@dataclass(frozen=True, slots=True)
class RecorderReconcileResult:
    desired_recording: bool
    changed: bool
    recording: bool
    event_prebuffer_required: bool


class RecordingRuntimeService:
    """Translate canonical policy into native ZLM recorder state.

    No recorder/session runtime rows are persisted. DB reads produce a pure
    desired object; callers must end the DB transaction before reconcile().
    """

    def __init__(
        self,
        settings: Settings,
        *,
        zlm_factory: Callable[[Settings], Any] = ZlmAdapter,
    ) -> None:
        self.settings = settings
        self._zlm_factory = zlm_factory

    @staticmethod
    def desired(
        session: Session,
        *,
        camera_id: uuid.UUID,
        at: datetime | None = None,
    ) -> DesiredRecorder | None:
        from .policy import RecordingPolicyService

        camera = session.get(Camera, camera_id)
        if camera is None:
            raise ApiError(
                status_code=404,
                code="camera_not_found",
                message="Camera was not found.",
            )

        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )
        if policy is None or not camera.enabled:
            return None

        binding = session.scalar(
            select(CameraStreamBinding).where(
                CameraStreamBinding.camera_id == camera_id,
                CameraStreamBinding.purpose == "RECORD",
            )
        )
        if binding is None:
            raise ApiError(
                status_code=409,
                code="recording_stream_binding_missing",
                message="Camera has no RECORD stream binding.",
            )

        profile = session.get(CameraStreamProfile, binding.stream_profile_id)
        if profile is None or profile.camera_id != camera.id:
            raise ApiError(
                status_code=409,
                code="recording_stream_binding_invalid",
                message="Camera RECORD stream binding is invalid.",
            )

        target = RecordingStorageResolver.local_target_for_camera(
            session,
            camera_id=camera_id,
        )
        reference = CameraMediaRuntimeService.reference_for(
            camera_id=camera.id,
            profile_id=profile.id,
        )
        instant = at or datetime.now(UTC)
        should_record = RecordingPolicyService.baseline_should_record(
            policy,
            at=instant,
        )
        event_prebuffer_required = (
            policy.enabled
            and policy.baseline_mode == "disabled"
            and policy.event_recording_enabled
        )

        return DesiredRecorder(
            camera_id=camera.id,
            profile_id=profile.id,
            app=reference.app,
            stream=reference.stream,
            target_root=str(target.root),
            segment_target_seconds=policy.segment_target_seconds,
            should_record=should_record,
            event_prebuffer_required=event_prebuffer_required,
        )

    def reconcile(
        self,
        desired: DesiredRecorder | None,
        *,
        explicit_stop_at: datetime | None = None,
    ) -> RecorderReconcileResult:
        if desired is None:
            return RecorderReconcileResult(
                desired_recording=False,
                changed=False,
                recording=False,
                event_prebuffer_required=False,
            )

        with self._zlm_factory(self.settings) as zlm:
            current = zlm.is_mp4_recording(
                app=desired.app,
                stream=desired.stream,
            )

            changed = False
            if desired.should_record and not current:
                if not zlm.start_mp4_recording(
                    app=desired.app,
                    stream=desired.stream,
                    customized_path=desired.target_root,
                    max_second=desired.segment_target_seconds,
                ):
                    raise ApiError(
                        status_code=503,
                        code="recording_start_failed",
                        message="ZLMediaKit did not start recording.",
                    )
                current = True
                changed = True

            elif not desired.should_record and current:
                if not zlm.stop_mp4_recording(
                    app=desired.app,
                    stream=desired.stream,
                ):
                    raise ApiError(
                        status_code=503,
                        code="recording_stop_failed",
                        message="ZLMediaKit did not stop recording.",
                    )
                current = False
                changed = True

        return RecorderReconcileResult(
            desired_recording=desired.should_record,
            changed=changed,
            recording=current,
            event_prebuffer_required=desired.event_prebuffer_required,
        )

    @staticmethod
    def finalize_explicit_stop_tail(
        session: Session,
        *,
        tracker: Any,
        desired: DesiredRecorder,
        boundary_at: datetime,
    ) -> uuid.UUID | None:
        resolution = tracker.closed_resolution(
            vhost="__defaultVhost__",
            app=desired.app,
            stream=desired.stream,
        )
        if resolution is None or resolution.previous_segment_id is None:
            return None

        finalized = RecordingCatalogService.finalize_provisional_segment(
            session,
            segment_id=resolution.previous_segment_id,
            boundary_at=boundary_at,
            timing_source="EXPLICIT_STOP",
        )
        return finalized.id if finalized is not None else None
