from __future__ import annotations

import uuid
from collections.abc import Callable


class StorageTaskDispatcher:
    """Thin Huey enqueue boundary for storage lifecycle work."""

    def __init__(
        self,
        *,
        archive_enqueue: Callable[[str, str], object] | None = None,
        playback_restore_enqueue: Callable[[str], object] | None = None,
    ) -> None:
        self._archive_enqueue = archive_enqueue
        self._playback_restore_enqueue = playback_restore_enqueue

    def archive_segment(
        self,
        *,
        segment_id: uuid.UUID,
        target_id: uuid.UUID,
    ) -> None:
        enqueue = self._archive_enqueue
        if enqueue is None:
            from app.worker.tasks import archive_recording_segment

            enqueue = archive_recording_segment

        enqueue(
            str(segment_id),
            str(target_id),
        )

    def restore_playback_segment(
        self,
        *,
        segment_id: uuid.UUID,
    ) -> None:
        enqueue = self._playback_restore_enqueue
        if enqueue is None:
            from app.worker.tasks import restore_playback_segment

            enqueue = restore_playback_segment

        enqueue(str(segment_id))

    @staticmethod
    def reconcile_retention(
        *,
        pressure: bool = False,
    ) -> None:
        from app.worker.tasks import reconcile_retention

        reconcile_retention(pressure)
