from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Database
from app.core.db.types import utc_now
from app.modules.cameras.models import Camera
from app.modules.recordings.models import RecordingSegment
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)
from app.modules.system.benchmark import (
    CameraBenchmarkStatus,
    ReleaseBenchmarkService,
)


class RealCameraAcceptanceService:
    format = "zero-nvr.real-camera-acceptance"
    format_version = 1

    def __init__(
        self,
        settings: Settings,
        database: Database,
        *,
        benchmark_factory: Callable[
            [Settings, Database],
            Any,
        ] = ReleaseBenchmarkService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.settings = settings
        self.database = database
        self._benchmark_factory = benchmark_factory
        self._clock = clock

    def state_path(
        self,
        camera_id: uuid.UUID,
    ) -> Path:
        return (
            self.settings.data_dir
            / "release-validation"
            / f"real-camera-{camera_id}.json"
        )

    @staticmethod
    def _iso(value: datetime) -> str:
        return (
            value.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _parse(value: str) -> datetime:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).astimezone(UTC)

    def _write_state(
        self,
        camera_id: uuid.UUID,
        value: dict[str, Any],
    ) -> None:
        path = self.state_path(camera_id)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".real-camera.",
            delete=False,
        ) as handle:
            json.dump(
                value,
                handle,
                sort_keys=True,
            )
            handle.write("\n")
            temporary = Path(handle.name)
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)

    def _read_state(
        self,
        camera_id: uuid.UUID,
    ) -> dict[str, Any]:
        path = self.state_path(camera_id)
        if not path.is_file():
            raise RuntimeError(
                "real-camera acceptance state is missing; "
                "run prepare first"
            )
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
        if (
            value.get("format") != self.format
            or value.get("format_version")
            != self.format_version
            or value.get("camera_id")
            != str(camera_id)
        ):
            raise RuntimeError(
                "real-camera acceptance state is incompatible"
            )
        return value

    def status(
        self,
        camera_id: uuid.UUID,
    ) -> dict[str, Any]:
        return self._read_state(
            camera_id
        )

    def _runtime(
        self,
        camera_id: uuid.UUID,
    ) -> tuple[
        Camera | None,
        CameraBenchmarkStatus | None,
        list[str],
    ]:
        failures: list[str] = []
        with self.database.session() as session:
            camera = session.get(
                Camera,
                camera_id,
            )
            if camera is None:
                return (
                    None,
                    None,
                    ["camera_missing"],
                )
            if not camera.enabled:
                failures.append(
                    "camera_disabled"
                )
            if camera.retired_at is not None:
                failures.append(
                    "camera_retired"
                )
            session.expunge(camera)
            session.commit()

        benchmark = self._benchmark_factory(
            self.settings,
            self.database,
        ).collect(
            expected_cameras=1,
        )
        camera_status = next(
            (
                item
                for item in benchmark.cameras
                if item.camera_id == camera_id
            ),
            None,
        )
        if camera_status is None:
            failures.append(
                "camera_runtime_missing"
            )
            return (
                camera,
                None,
                failures,
            )
        if (
            camera_status.desired_mode
            != "persistent"
        ):
            failures.append(
                "camera_not_persistent_recording"
            )
        if (
            camera_status.stream_online
            is not True
        ):
            failures.append(
                "record_stream_not_online"
            )
        if (
            camera_status.recording_active
            is not True
        ):
            failures.append(
                "mp4_recorder_not_active"
            )
        if camera_status.error is not None:
            failures.append(
                f"camera_runtime:{camera_status.error}"
            )
        return (
            camera,
            camera_status,
            failures,
        )

    @staticmethod
    def _segment_payload(
        segment: RecordingSegment,
        location: RecordingLocation,
        target: StorageTarget,
    ) -> dict[str, Any]:
        return {
            "segment_id": str(
                segment.id
            ),
            "location_id": str(
                location.id
            ),
            "storage_target_id": str(
                target.id
            ),
            "object_path": (
                location.object_path
            ),
            "location_size_bytes": (
                location.size_bytes
            ),
            "segment_size_bytes": (
                segment.size_bytes
            ),
            "started_at": (
                RealCameraAcceptanceService
                ._iso(segment.started_at)
            ),
            "ended_at": (
                RealCameraAcceptanceService
                ._iso(segment.ended_at)
            ),
            "created_at": (
                RealCameraAcceptanceService
                ._iso(segment.created_at)
            ),
            "timing_status": (
                segment.timing_status
            ),
            "timing_source": (
                segment.timing_source
            ),
            "completion_reason": (
                segment.completion_reason
            ),
            "source_media_server_id": (
                segment.source_media_server_id
            ),
            "source_app": (
                segment.source_app
            ),
            "source_stream": (
                segment.source_stream
            ),
        }

    def _latest_hook_segment(
        self,
        camera_id: uuid.UUID,
        *,
        created_after: datetime | None = None,
        exclude_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        with self.database.session() as session:
            statement = (
                select(
                    RecordingSegment,
                    RecordingLocation,
                    StorageTarget,
                )
                .join(
                    RecordingLocation,
                    RecordingLocation.recording_segment_id
                    == RecordingSegment.id,
                )
                .join(
                    StorageTarget,
                    StorageTarget.id
                    == RecordingLocation.storage_target_id,
                )
                .where(
                    RecordingSegment.camera_id
                    == camera_id,
                    RecordingSegment.timing_status
                    == "FINAL",
                    RecordingSegment.timing_source.in_(
                        (
                            "NEXT_SEGMENT_BOUNDARY",
                            "EXPLICIT_STOP",
                        )
                    ),
                    RecordingSegment.size_bytes
                    > 0,
                    RecordingLocation.state
                    == "AVAILABLE",
                    StorageTarget.type
                    == "local",
                    StorageTarget.role
                    == "recording",
                )
            )
            if created_after is not None:
                statement = statement.where(
                    RecordingSegment.created_at
                    > created_after
                )
            if exclude_id is not None:
                statement = statement.where(
                    RecordingSegment.id
                    != exclude_id
                )
            row = session.execute(
                statement.order_by(
                    RecordingSegment.created_at.desc(),
                    RecordingSegment.id.desc(),
                ).limit(1)
            ).first()
            if row is None:
                session.commit()
                return None
            segment, location, target = row
            payload = self._segment_payload(
                segment,
                location,
                target,
            )
            session.commit()
            return payload

    def prepare(
        self,
        camera_id: uuid.UUID,
    ) -> dict[str, Any]:
        camera, runtime, failures = (
            self._runtime(camera_id)
        )
        baseline = self._latest_hook_segment(
            camera_id
        )
        if baseline is None:
            failures.append(
                "finalized_hook_segment_missing"
            )

        prepared_at = self._clock()
        result = {
            "format": self.format,
            "format_version": (
                self.format_version
            ),
            "phase": "prepared",
            "passed": not failures,
            "camera_id": str(camera_id),
            "camera_name": (
                camera.name
                if camera is not None
                else None
            ),
            "camera_config_revision": (
                camera.config_revision
                if camera is not None
                else None
            ),
            "prepared_at": (
                self._iso(prepared_at)
            ),
            "runtime": {
                "desired_mode": (
                    runtime.desired_mode
                    if runtime is not None
                    else None
                ),
                "stream_online": (
                    runtime.stream_online
                    if runtime is not None
                    else None
                ),
                "recording_active": (
                    runtime.recording_active
                    if runtime is not None
                    else None
                ),
                "error": (
                    runtime.error
                    if runtime is not None
                    else None
                ),
            },
            "baseline_segment": baseline,
            "restart_completed_at": None,
            "verification": None,
            "failures": failures,
        }
        if not failures:
            self._write_state(
                camera_id,
                result,
            )
        return result

    def mark_restart(
        self,
        camera_id: uuid.UUID,
    ) -> dict[str, Any]:
        state = self._read_state(
            camera_id
        )
        state["phase"] = "restarted"
        state["restart_completed_at"] = (
            self._iso(self._clock())
        )
        state["verification"] = None
        self._write_state(
            camera_id,
            state,
        )
        return state

    def _baseline_failures(
        self,
        camera_id: uuid.UUID,
        baseline: dict[str, Any],
    ) -> list[str]:
        failures: list[str] = []
        try:
            segment_id = uuid.UUID(
                str(
                    baseline[
                        "segment_id"
                    ]
                )
            )
            location_id = uuid.UUID(
                str(
                    baseline[
                        "location_id"
                    ]
                )
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return [
                "baseline_identity_invalid"
            ]

        with self.database.session() as session:
            segment = session.get(
                RecordingSegment,
                segment_id,
            )
            location = session.get(
                RecordingLocation,
                location_id,
            )
            if segment is None:
                failures.append(
                    "baseline_segment_missing"
                )
            if location is None:
                failures.append(
                    "baseline_location_missing"
                )

            if segment is not None:
                if (
                    segment.camera_id
                    != camera_id
                    or segment.timing_status
                    != "FINAL"
                    or segment.timing_source
                    not in {
                        "NEXT_SEGMENT_BOUNDARY",
                        "EXPLICIT_STOP",
                    }
                    or segment.size_bytes
                    != baseline.get(
                        "segment_size_bytes"
                    )
                    or self._iso(
                        segment.started_at
                    )
                    != baseline.get(
                        "started_at"
                    )
                    or self._iso(
                        segment.ended_at
                    )
                    != baseline.get(
                        "ended_at"
                    )
                ):
                    failures.append(
                        "baseline_segment_changed"
                    )

            if location is not None:
                target = session.get(
                    StorageTarget,
                    location.storage_target_id,
                )
                if (
                    location.recording_segment_id
                    != segment_id
                    or location.state
                    != "AVAILABLE"
                    or location.object_path
                    != baseline.get(
                        "object_path"
                    )
                    or location.size_bytes
                    != baseline.get(
                        "location_size_bytes"
                    )
                    or target is None
                    or target.type != "local"
                ):
                    failures.append(
                        "baseline_location_changed"
                    )

            if segment is not None:
                duplicate_count = int(
                    session.scalar(
                        select(
                            func.count(
                                RecordingSegment.id
                            )
                        ).where(
                            RecordingSegment.camera_id
                            == camera_id,
                            RecordingSegment.source_media_server_id
                            == baseline.get(
                                "source_media_server_id"
                            ),
                            RecordingSegment.source_app
                            == baseline.get(
                                "source_app"
                            ),
                            RecordingSegment.source_stream
                            == baseline.get(
                                "source_stream"
                            ),
                            RecordingSegment.started_at
                            == self._parse(
                                str(
                                    baseline[
                                        "started_at"
                                    ]
                                )
                            ),
                            RecordingSegment.ended_at
                            == self._parse(
                                str(
                                    baseline[
                                        "ended_at"
                                    ]
                                )
                            ),
                        )
                    )
                    or 0
                )
                if duplicate_count != 1:
                    failures.append(
                        "baseline_segment_duplicated"
                    )
            session.commit()
        return failures

    def verify(
        self,
        camera_id: uuid.UUID,
        *,
        live_confirmed: bool,
        playback_confirmed: bool,
    ) -> dict[str, Any]:
        state = self._read_state(
            camera_id
        )
        failures: list[str] = []

        restart_raw = state.get(
            "restart_completed_at"
        )
        if not isinstance(
            restart_raw,
            str,
        ):
            failures.append(
                "restart_not_completed"
            )
            restart_at = None
        else:
            restart_at = self._parse(
                restart_raw
            )

        camera, runtime, runtime_failures = (
            self._runtime(camera_id)
        )
        failures.extend(
            runtime_failures
        )
        if camera is None:
            failures.append(
                "camera_identity_missing"
            )

        baseline = state.get(
            "baseline_segment"
        )
        if not isinstance(
            baseline,
            dict,
        ):
            failures.append(
                "baseline_segment_missing"
            )
            baseline_id = None
        else:
            failures.extend(
                self._baseline_failures(
                    camera_id,
                    baseline,
                )
            )
            try:
                baseline_id = uuid.UUID(
                    str(
                        baseline[
                            "segment_id"
                        ]
                    )
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                baseline_id = None

        post_restart_segment = None
        if restart_at is not None:
            post_restart_segment = (
                self._latest_hook_segment(
                    camera_id,
                    created_after=restart_at,
                    exclude_id=baseline_id,
                )
            )
            if post_restart_segment is None:
                failures.append(
                    "post_restart_finalized_hook_segment_missing"
                )

        if not live_confirmed:
            failures.append(
                "live_view_not_confirmed"
            )
        if not playback_confirmed:
            failures.append(
                "timeline_playback_not_confirmed"
            )

        verification = {
            "passed": not failures,
            "verified_at": (
                self._iso(
                    self._clock()
                )
            ),
            "camera_id": str(
                camera_id
            ),
            "camera_name": (
                camera.name
                if camera is not None
                else None
            ),
            "runtime": {
                "desired_mode": (
                    runtime.desired_mode
                    if runtime is not None
                    else None
                ),
                "stream_online": (
                    runtime.stream_online
                    if runtime is not None
                    else None
                ),
                "recording_active": (
                    runtime.recording_active
                    if runtime is not None
                    else None
                ),
                "error": (
                    runtime.error
                    if runtime is not None
                    else None
                ),
            },
            "manual": {
                "live_confirmed": (
                    live_confirmed
                ),
                "timeline_playback_confirmed": (
                    playback_confirmed
                ),
            },
            "post_restart_segment": (
                post_restart_segment
            ),
            "failures": failures,
        }
        state["phase"] = (
            "verified"
            if not failures
            else "verification_failed"
        )
        state["verification"] = (
            verification
        )
        state["passed"] = (
            not failures
        )
        self._write_state(
            camera_id,
            state,
        )
        return state
