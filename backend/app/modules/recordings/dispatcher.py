from __future__ import annotations

import uuid

from app.core.config import Settings
from app.core.db import Database
from app.modules.recordings.prebuffer import PrebufferFragment
from app.modules.system.settings import (
    RuntimeTuningSettingsService,
)


class RecordingTaskDispatcher:
    """Thin enqueue boundary so API/hooks do not own worker mechanics."""

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
    ) -> None:
        self.settings = settings
        self.database = database

    def _prebuffer_buffer_seconds(self) -> int:
        if self.database is None:
            return (
                RuntimeTuningSettingsService
                .defaults(self.settings)
                .prebuffer_buffer_seconds
            )
        with self.database.session() as session:
            return (
                RuntimeTuningSettingsService
                .get(
                    session,
                    settings=self.settings,
                )
                .prebuffer_buffer_seconds
            )

    @staticmethod
    def _args(fragment: PrebufferFragment) -> tuple[object, ...]:
        return (
            str(fragment.camera_id),
            str(fragment.profile_id),
            (
                str(fragment.continuity_id)
                if fragment.continuity_id is not None
                else None
            ),
            fragment.vhost,
            fragment.app,
            fragment.stream,
            str(fragment.file_path),
            fragment.started_at.timestamp(),
            fragment.duration_ms / 1000.0,
            fragment.size_bytes,
        )

    def finalized_prebuffer_fragment(
        self,
        fragment: PrebufferFragment,
    ) -> None:
        from app.worker.tasks import (
            gc_prebuffer_fragment,
            promote_prebuffer_fragment,
        )

        args = self._args(fragment)
        promote_prebuffer_fragment(*args)
        gc_prebuffer_fragment.schedule(
            args=args,
            delay=self._prebuffer_buffer_seconds(),
        )

    @staticmethod
    def reconcile_camera(camera_id: uuid.UUID) -> None:
        from app.worker.tasks import reconcile_camera_prebuffer

        reconcile_camera_prebuffer(str(camera_id))

    @staticmethod
    def reconcile_runtime(
        camera_id: uuid.UUID,
        *,
        restart_streams: bool = False,
        force_reconfigure: bool = False,
        restart_profile_ids: tuple[
            uuid.UUID,
            ...,
        ] = (),
    ) -> None:
        from app.worker.tasks import reconcile_camera_runtime

        reconcile_camera_runtime(
            str(camera_id),
            restart_streams,
            force_reconfigure,
            tuple(
                str(profile_id)
                for profile_id
                in restart_profile_ids
            ),
        )

    @staticmethod
    def schedule_runtime(
        camera_id: uuid.UUID,
        *,
        eta,
        force_reconfigure: bool = False,
    ) -> None:
        from app.worker.tasks import (
            reconcile_camera_runtime,
        )

        reconcile_camera_runtime.schedule(
            args=(
                str(camera_id),
                False,
                force_reconfigure,
            ),
            eta=eta,
        )

    @staticmethod
    def schedule_manual_boundary(
        camera_id: uuid.UUID,
        *,
        eta,
    ) -> None:
        from app.worker.tasks import (
            reconcile_manual_recording_boundary,
        )

        reconcile_manual_recording_boundary.schedule(
            args=(str(camera_id),),
            eta=eta,
        )

    @staticmethod
    def reconcile_catalog(
        *,
        full: bool = False,
    ) -> None:
        from app.worker.tasks import (
            reconcile_recording_catalog,
        )

        reconcile_recording_catalog(
            full
        )

    @staticmethod
    def schedule_policy(
        *,
        policy_id: uuid.UUID,
        policy_version: str,
        eta,
    ) -> None:
        from app.worker.tasks import reconcile_recording_policy_boundary

        reconcile_recording_policy_boundary.schedule(
            args=(str(policy_id), policy_version),
            eta=eta,
        )
