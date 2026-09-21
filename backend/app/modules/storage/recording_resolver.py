from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.recordings.models import RecordingPolicy

from .capacity import (
    LocalStorageCapacity,
    LocalStorageCapacityService,
)
from .models import StorageTarget


@dataclass(frozen=True, slots=True)
class LocalRecordingTarget:
    target: StorageTarget
    root: Path


class RecordingStorageResolver:
    @staticmethod
    def local_target_for_camera(
        session: Session,
        *,
        camera_id: uuid.UUID,
    ) -> LocalRecordingTarget:
        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )

        target: StorageTarget | None = None
        if policy is not None and policy.storage_target_id is not None:
            target = session.get(StorageTarget, policy.storage_target_id)
            if target is None:
                raise ApiError(
                    status_code=409,
                    code="recording_storage_target_missing",
                    message="Recording storage target is unavailable.",
                )
        else:
            candidates = list(
                session.scalars(
                    select(StorageTarget).where(
                        StorageTarget.type == "local",
                        StorageTarget.role == "recording",
                        StorageTarget.enabled.is_(True),
                    )
                )
            )
            defaults = [
                item
                for item in candidates
                if bool((item.config_json or {}).get("default_recording"))
            ]
            if len(defaults) == 1:
                target = defaults[0]
            elif len(defaults) > 1:
                raise ApiError(
                    status_code=409,
                    code="recording_storage_target_ambiguous",
                    message="More than one default recording storage target is configured.",
                )
            elif len(candidates) == 1:
                target = candidates[0]

        if target is None:
            raise ApiError(
                status_code=409,
                code="recording_storage_target_unconfigured",
                message="No local recording storage target is configured.",
            )
        if (
            target.type != "local"
            or target.role != "recording"
            or not target.enabled
        ):
            raise ApiError(
                status_code=409,
                code="recording_storage_target_invalid",
                message="Selected recording storage target is not available for local recording.",
            )

        config = target.config_json or {}
        raw_path = config.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ApiError(
                status_code=409,
                code="recording_storage_path_unconfigured",
                message="Recording storage target has no local path.",
            )

        root = Path(raw_path).expanduser()
        if not root.is_absolute():
            raise ApiError(
                status_code=409,
                code="recording_storage_path_invalid",
                message="Recording storage target path must be absolute.",
            )

        return LocalRecordingTarget(
            target=target,
            root=root.resolve(strict=False),
        )

    @staticmethod
    def ensure_write_capacity(
        target: LocalRecordingTarget,
    ) -> LocalStorageCapacity:
        return (
            LocalStorageCapacityService
            .ensure_write_capacity(
                root=target.root,
                config=(
                    target.target
                    .config_json
                    or {}
                ),
            )
        )


    @staticmethod
    def relative_object_path(
        *,
        target_root: Path,
        file_path: str,
    ) -> str:
        candidate = Path(file_path).expanduser()
        if not candidate.is_absolute():
            raise ApiError(
                status_code=422,
                code="recording_file_path_invalid",
                message="Recording file path must be absolute.",
            )

        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(target_root)
        except ValueError as exc:
            raise ApiError(
                status_code=422,
                code="recording_file_outside_target",
                message="Recording file is outside the configured storage target.",
            ) from exc

        if not relative.parts:
            raise ApiError(
                status_code=422,
                code="recording_file_path_invalid",
                message="Recording file path is invalid.",
            )
        return relative.as_posix()
