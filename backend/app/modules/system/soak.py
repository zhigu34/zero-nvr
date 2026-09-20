from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Database
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
)
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)

from .benchmark import (
    CameraBenchmarkStatus,
    ReleaseBenchmarkService,
    ReleaseBenchmarkStatus,
)
from .health import (
    ProductHealth,
    SystemHealthService,
)


@dataclass(frozen=True, slots=True)
class PersistentRecordingProgress:
    camera_id: uuid.UUID
    name: str
    segment_target_seconds: int
    segments_since_start: int
    available_local_segments_since_start: int
    bytes_since_start: int
    latest_segment_created_at: datetime | None
    passed: bool


@dataclass(frozen=True, slots=True)
class ReleaseSoakStatus:
    expected_cameras: int
    sampled_at: datetime
    since: datetime
    runtime: ReleaseBenchmarkStatus
    required_health: dict[str, str]
    persistent_progress: tuple[
        PersistentRecordingProgress,
        ...,
    ]
    progress_required: bool
    passed: bool
    failures: tuple[str, ...]


class ReleaseSoakService:
    required_health_components = (
        "database",
        "worker",
        "zlmediakit",
        "storage",
    )

    def __init__(
        self,
        settings: Settings,
        database: Database,
        *,
        benchmark_factory: Callable[
            [Settings, Database],
            ReleaseBenchmarkService,
        ] = ReleaseBenchmarkService,
        health_factory: Callable[
            [Settings, Database],
            SystemHealthService,
        ] = SystemHealthService,
    ) -> None:
        self.settings = settings
        self.database = database
        self._benchmark_factory = benchmark_factory
        self._health_factory = health_factory

    @staticmethod
    def _persistent_cameras(
        runtime: ReleaseBenchmarkStatus,
    ) -> list[CameraBenchmarkStatus]:
        return [
            item
            for item in runtime.cameras
            if item.desired_mode == "persistent"
            and item.error is None
        ]

    def _progress(
        self,
        *,
        runtime: ReleaseBenchmarkStatus,
        since: datetime,
    ) -> tuple[PersistentRecordingProgress, ...]:
        persistent = self._persistent_cameras(
            runtime
        )
        if not persistent:
            return ()

        names = {
            item.camera_id: item.name
            for item in persistent
        }
        camera_ids = set(names)

        with self.database.session() as session:
            policies = {
                item.camera_id: item
                for item in session.scalars(
                    select(RecordingPolicy).where(
                        RecordingPolicy.camera_id.in_(
                            camera_ids
                        )
                    )
                )
            }

            rows = session.execute(
                select(
                    RecordingSegment.camera_id,
                    func.count(
                        RecordingSegment.id
                    ).label("segments"),
                    func.coalesce(
                        func.sum(
                            RecordingSegment.size_bytes
                        ),
                        0,
                    ).label("bytes"),
                    func.max(
                        RecordingSegment.created_at
                    ).label("latest"),
                )
                .where(
                    RecordingSegment.camera_id.in_(
                        camera_ids
                    ),
                    RecordingSegment.created_at
                    >= since,
                )
                .group_by(
                    RecordingSegment.camera_id
                )
            ).all()

            available_rows = session.execute(
                select(
                    RecordingSegment.camera_id,
                    func.count(
                        func.distinct(
                            RecordingSegment.id
                        )
                    ).label("available"),
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
                    RecordingSegment.camera_id.in_(
                        camera_ids
                    ),
                    RecordingSegment.created_at
                    >= since,
                    RecordingLocation.state
                    == "AVAILABLE",
                    StorageTarget.type == "local",
                    StorageTarget.role == "recording",
                )
                .group_by(
                    RecordingSegment.camera_id
                )
            ).all()
            session.commit()

        totals = {
            camera_id: (
                int(segments),
                int(size_bytes),
                latest,
            )
            for (
                camera_id,
                segments,
                size_bytes,
                latest,
            ) in rows
        }
        available = {
            camera_id: int(count)
            for camera_id, count in available_rows
        }

        result: list[
            PersistentRecordingProgress
        ] = []
        for camera_id in sorted(
            camera_ids,
            key=lambda value: (
                names[value].casefold(),
                str(value),
            ),
        ):
            policy = policies.get(camera_id)
            target = (
                policy.segment_target_seconds
                if policy is not None
                else 0
            )
            segments, size_bytes, latest = (
                totals.get(
                    camera_id,
                    (0, 0, None),
                )
            )
            local_available = available.get(
                camera_id,
                0,
            )
            result.append(
                PersistentRecordingProgress(
                    camera_id=camera_id,
                    name=names[camera_id],
                    segment_target_seconds=target,
                    segments_since_start=segments,
                    available_local_segments_since_start=(
                        local_available
                    ),
                    bytes_since_start=size_bytes,
                    latest_segment_created_at=latest,
                    passed=(
                        segments > 0
                        and local_available > 0
                        and size_bytes > 0
                    ),
                )
            )
        return tuple(result)

    def collect(
        self,
        *,
        expected_cameras: int,
        since: datetime,
        require_progress: bool,
    ) -> ReleaseSoakStatus:
        if since.tzinfo is None:
            raise ValueError(
                "soak start time must include a timezone"
            )
        normalized_since = since.astimezone(UTC)
        sampled_at = datetime.now(UTC)

        runtime = self._benchmark_factory(
            self.settings,
            self.database,
        ).collect(
            expected_cameras=expected_cameras,
        )
        health: ProductHealth = (
            self._health_factory(
                self.settings,
                self.database,
            ).collect()
        )
        required_health = {
            name: (
                health.components[name].status
                if name in health.components
                else "MISSING"
            )
            for name in self.required_health_components
        }
        progress = self._progress(
            runtime=runtime,
            since=normalized_since,
        )

        failures: list[str] = []
        if not runtime.passed:
            failures.append(
                "runtime_gate_failed"
            )
        for name, status in (
            required_health.items()
        ):
            if status != "OK":
                failures.append(
                    f"health_{name}_{status.lower()}"
                )

        if require_progress:
            persistent_count = len(
                self._persistent_cameras(runtime)
            )
            if persistent_count:
                failed_progress = [
                    item
                    for item in progress
                    if not item.passed
                ]
                if failed_progress:
                    failures.append(
                        "persistent_recording_progress_failed"
                    )

        return ReleaseSoakStatus(
            expected_cameras=expected_cameras,
            sampled_at=sampled_at,
            since=normalized_since,
            runtime=runtime,
            required_health=required_health,
            persistent_progress=progress,
            progress_required=require_progress,
            passed=not failures,
            failures=tuple(failures),
        )
