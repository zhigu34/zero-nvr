from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ApiError
from app.integrations.zlm import (
    ZlmAdapter,
    ZlmIntegrationError,
)
from app.modules.cameras.models import Camera
from app.modules.recordings.runtime import (
    DesiredRecorder,
    RecordingRuntimeService,
)


@dataclass(frozen=True, slots=True)
class CameraBenchmarkStatus:
    camera_id: uuid.UUID
    name: str
    desired_mode: str | None
    stream_online: bool | None
    recording_active: bool | None
    error: str | None


@dataclass(frozen=True, slots=True)
class ReleaseBenchmarkStatus:
    expected_cameras: int
    enabled_cameras: int
    recording_expected_cameras: int
    record_streams_online: int
    recorders_active: int
    passed: bool
    failures: tuple[str, ...]
    cameras: tuple[CameraBenchmarkStatus, ...]


class ReleaseBenchmarkService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        *,
        zlm_factory: Callable[[Settings], Any] = ZlmAdapter,
    ) -> None:
        self.settings = settings
        self.database = database
        self._zlm_factory = zlm_factory

    def collect(
        self,
        *,
        expected_cameras: int,
    ) -> ReleaseBenchmarkStatus:
        if expected_cameras <= 0:
            raise ValueError(
                "expected_cameras must be greater than zero"
            )

        planned: list[
            tuple[Camera, DesiredRecorder | None, str | None]
        ] = []
        with self.database.session() as session:
            cameras = list(
                session.scalars(
                    select(Camera)
                    .where(
                        Camera.enabled.is_(True),
                        Camera.retired_at.is_(None),
                    )
                    .order_by(
                        Camera.name,
                        Camera.id,
                    )
                )
            )
            for camera in cameras:
                desired: DesiredRecorder | None = None
                error: str | None = None
                try:
                    desired = RecordingRuntimeService.desired(
                        session,
                        settings=self.settings,
                        camera_id=camera.id,
                    )
                    if desired is None:
                        error = "recording_policy_missing"
                except ApiError as exc:
                    error = exc.code
                planned.append(
                    (
                        camera,
                        desired,
                        error,
                    )
                )
            session.commit()

        results: list[CameraBenchmarkStatus] = []
        active_plans = [
            item
            for item in planned
            if item[1] is not None
            and item[1].mode != "off"
            and item[2] is None
        ]

        observations: dict[
            uuid.UUID,
            tuple[bool | None, bool | None, str | None],
        ] = {}

        if active_plans:
            try:
                with self._zlm_factory(
                    self.settings
                ) as zlm:
                    for camera, desired, _error in active_plans:
                        assert desired is not None
                        try:
                            online = zlm.is_media_online(
                                app=desired.app,
                                stream=desired.stream,
                            )
                            recording = (
                                zlm.is_mp4_recording(
                                    app=desired.app,
                                    stream=desired.stream,
                                )
                                if online
                                else False
                            )
                            observations[camera.id] = (
                                online,
                                recording,
                                None,
                            )
                        except ZlmIntegrationError as exc:
                            observations[camera.id] = (
                                None,
                                None,
                                exc.code,
                            )
            except ZlmIntegrationError as exc:
                for camera, _desired, _error in active_plans:
                    observations[camera.id] = (
                        None,
                        None,
                        exc.code,
                    )

        for camera, desired, planned_error in planned:
            desired_mode = (
                desired.mode
                if desired is not None
                else None
            )
            if planned_error is not None:
                results.append(
                    CameraBenchmarkStatus(
                        camera_id=camera.id,
                        name=camera.name,
                        desired_mode=desired_mode,
                        stream_online=None,
                        recording_active=None,
                        error=planned_error,
                    )
                )
                continue

            if desired is None:
                results.append(
                    CameraBenchmarkStatus(
                        camera_id=camera.id,
                        name=camera.name,
                        desired_mode=None,
                        stream_online=None,
                        recording_active=None,
                        error="recording_policy_missing",
                    )
                )
                continue

            if desired.mode == "off":
                results.append(
                    CameraBenchmarkStatus(
                        camera_id=camera.id,
                        name=camera.name,
                        desired_mode="off",
                        stream_online=None,
                        recording_active=False,
                        error=None,
                    )
                )
                continue

            online, recording, error = observations.get(
                camera.id,
                (None, None, "zlm_observation_missing"),
            )
            results.append(
                CameraBenchmarkStatus(
                    camera_id=camera.id,
                    name=camera.name,
                    desired_mode=desired.mode,
                    stream_online=online,
                    recording_active=recording,
                    error=error,
                )
            )

        recording_expected = sum(
            1
            for item in results
            if item.desired_mode
            in {"persistent", "prebuffer"}
            and item.error is None
        )
        online_count = sum(
            1
            for item in results
            if item.stream_online is True
        )
        recording_count = sum(
            1
            for item in results
            if item.recording_active is True
        )

        failures: list[str] = []
        if len(results) < expected_cameras:
            failures.append(
                "enabled_camera_count_below_target"
            )
        if recording_expected < expected_cameras:
            failures.append(
                "recording_camera_count_below_target"
            )
        if online_count < expected_cameras:
            failures.append(
                "record_stream_online_count_below_target"
            )
        if recording_count < expected_cameras:
            failures.append(
                "active_recorder_count_below_target"
            )

        return ReleaseBenchmarkStatus(
            expected_cameras=expected_cameras,
            enabled_cameras=len(results),
            recording_expected_cameras=recording_expected,
            record_streams_online=online_count,
            recorders_active=recording_count,
            passed=not failures,
            failures=tuple(failures),
            cameras=tuple(results),
        )
