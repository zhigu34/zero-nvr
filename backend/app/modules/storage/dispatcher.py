from __future__ import annotations

import uuid


class StorageTaskDispatcher:
    """Thin Huey enqueue boundary for storage lifecycle work."""

    @staticmethod
    def archive_segment(
        *,
        segment_id: uuid.UUID,
        target_id: uuid.UUID,
    ) -> None:
        from app.worker.tasks import archive_recording_segment

        archive_recording_segment(
            str(segment_id),
            str(target_id),
        )
