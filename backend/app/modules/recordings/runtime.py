from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.integrations.zlm import ZlmAdapter
from app.modules.cameras.media_runtime import CameraMediaRuntimeService
from app.modules.cameras.models import Camera, CameraStreamBinding, CameraStreamProfile
from app.modules.storage.recording_resolver import RecordingStorageResolver

from .prebuffer import validate_prebuffer_root

from .catalog import RecordingCatalogService
from .models import RecordingPolicy
from .prebuffer_mount import PrebufferMountService


RecorderMode = Literal["persistent", "prebuffer", "off"]


@dataclass(frozen=True, slots=True)
class DesiredRecorder:
    camera_id: uuid.UUID
    profile_id: uuid.UUID
    app: str
    stream: str
    mode: RecorderMode
    target_root: str | None
    max_second: int


@dataclass(frozen=True, slots=True)
class RecorderReconcileResult:
    desired_mode: RecorderMode
    observed_recording: bool
    changed: bool
    assumed_existing_mode: bool


class RecorderModeTracker:
    """Process-local knowledge of recorder configuration.

    It deliberately does not persist recorder/session state. After an API
    restart an already-running ZLM recorder has unknown mode; ordinary
    reconciliation will not restart it merely to rediscover its path.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._modes: dict[tuple[str, str], RecorderMode] = {}

    def get(self, *, app: str, stream: str) -> RecorderMode | None:
        with self._lock:
            return self._modes.get((app, stream))

    def set(
        self,
        *,
        app: str,
        stream: str,
        mode: RecorderMode,
    ) -> None:
        with self._lock:
            if mode == "off":
                self._modes.pop((app, stream), None)
            else:
                self._modes[(app, stream)] = mode


class RecordingRuntimeService:
    """Translate canonical policy into one native ZLM MP4 recorder.

    Modes are mutually exclusive:
    - persistent: normal local recording;
    - prebuffer: short fragments in the bounded tmpfs mount;
    - off: no MP4 recorder.

    No RecordingSession/RecorderState rows are created.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        zlm_factory: Callable[[Settings], Any] = ZlmAdapter,
        mode_tracker: RecorderModeTracker | None = None,
    ) -> None:
        self.settings = settings
        self._zlm_factory = zlm_factory
        self.mode_tracker = mode_tracker or RecorderModeTracker()

    @staticmethod
    def desired(
        session: Session,
        *,
        settings: Settings,
        camera_id: uuid.UUID,
        at: datetime | None = None,
        capacity_behavior: Literal[
            "error",
            "off",
        ] = "error",
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
        if policy is None:
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

        reference = CameraMediaRuntimeService.reference_for(
            camera_id=camera.id,
            profile_id=profile.id,
        )

        instant = at or datetime.now(UTC)
        baseline_recording = (
            camera.enabled
            and RecordingPolicyService.baseline_should_record(
                policy,
                at=instant,
            )
        )
        event_prebuffer = (
            camera.enabled
            and policy.enabled
            and policy.event_recording_enabled
            and not baseline_recording
        )

        if baseline_recording:
            target = RecordingStorageResolver.local_target_for_camera(
                session,
                camera_id=camera_id,
            )
            try:
                RecordingStorageResolver.ensure_write_capacity(
                    target
                )
            except ApiError as exc:
                if (
                    exc.code
                    == "recording_storage_capacity_critical"
                    and capacity_behavior
                    == "off"
                ):
                    mode: RecorderMode = "off"
                    root: str | None = None
                    max_second = 0
                else:
                    raise
            else:
                mode = "persistent"
                root = str(target.root)
                max_second = policy.segment_target_seconds
        elif event_prebuffer:
            mode = "prebuffer"
            root = str(validate_prebuffer_root(settings))
            max_second = settings.prebuffer_fragment_seconds
        else:
            mode = "off"
            root = None
            max_second = 0

        return DesiredRecorder(
            camera_id=camera.id,
            profile_id=profile.id,
            app=reference.app,
            stream=reference.stream,
            mode=mode,
            target_root=root,
            max_second=max_second,
        )

    def reconcile(
        self,
        desired: DesiredRecorder | None,
        *,
        force_reconfigure: bool = False,
    ) -> RecorderReconcileResult:
        if desired is None:
            return RecorderReconcileResult(
                desired_mode="off",
                observed_recording=False,
                changed=False,
                assumed_existing_mode=False,
            )

        known_mode = self.mode_tracker.get(
            app=desired.app,
            stream=desired.stream,
        )

        with self._zlm_factory(self.settings) as zlm:
            online = zlm.is_media_online(
                app=desired.app,
                stream=desired.stream,
            )
            changed = False
            assumed = False

            if desired.mode == "off" and not online:
                self.mode_tracker.set(
                    app=desired.app,
                    stream=desired.stream,
                    mode="off",
                )
                return RecorderReconcileResult(
                    desired_mode="off",
                    observed_recording=False,
                    changed=False,
                    assumed_existing_mode=False,
                )

            if not online:
                raise ApiError(
                    status_code=503,
                    code="recording_stream_offline",
                    message="Camera recording stream is not available in ZLMediaKit.",
                )

            current = zlm.is_mp4_recording(
                app=desired.app,
                stream=desired.stream,
            )

            if desired.mode == "off":
                if current:
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
                self.mode_tracker.set(
                    app=desired.app,
                    stream=desired.stream,
                    mode="off",
                )
                return RecorderReconcileResult(
                    desired_mode="off",
                    observed_recording=current,
                    changed=changed,
                    assumed_existing_mode=False,
                )

            if desired.target_root is None:
                raise ApiError(
                    status_code=500,
                    code="recording_runtime_invalid",
                    message="Recording runtime target is unavailable.",
                )

            if current:
                if known_mode == desired.mode and not force_reconfigure:
                    return RecorderReconcileResult(
                        desired_mode=desired.mode,
                        observed_recording=True,
                        changed=False,
                        assumed_existing_mode=False,
                    )

                if known_mode is None and not force_reconfigure:
                    # ZLM recorder intentionally survives control-plane restart.
                    # With no process-local path proof, do not interrupt it just
                    # to rediscover whether it targets persistent storage or the
                    # prebuffer mount.
                    return RecorderReconcileResult(
                        desired_mode=desired.mode,
                        observed_recording=True,
                        changed=False,
                        assumed_existing_mode=True,
                    )

                if known_mode != desired.mode or force_reconfigure:
                    if not zlm.stop_mp4_recording(
                        app=desired.app,
                        stream=desired.stream,
                    ):
                        raise ApiError(
                            status_code=503,
                            code="recording_stop_failed",
                            message="ZLMediaKit did not stop the previous recorder mode.",
                        )
                    current = False
                    changed = True

            if not current:
                if not zlm.start_mp4_recording(
                    app=desired.app,
                    stream=desired.stream,
                    customized_path=desired.target_root,
                    max_second=desired.max_second,
                ):
                    raise ApiError(
                        status_code=503,
                        code="recording_start_failed",
                        message="ZLMediaKit did not start recording.",
                    )
                current = True
                changed = True

            self.mode_tracker.set(
                app=desired.app,
                stream=desired.stream,
                mode=desired.mode,
            )

        return RecorderReconcileResult(
            desired_mode=desired.mode,
            observed_recording=current,
            changed=changed,
            assumed_existing_mode=assumed,
        )

    @staticmethod
    def finalize_explicit_stop_tail(
        session: Session,
        *,
        tracker: Any,
        desired: DesiredRecorder,
        boundary_at: datetime,
    ) -> uuid.UUID | None:
        resolution = tracker.active_resolution(
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
