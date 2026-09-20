from __future__ import annotations

import uuid


class BackupTaskDispatcher:
    @staticmethod
    def run(backup_set_id: uuid.UUID) -> None:
        from app.worker.tasks import run_backup_set

        run_backup_set(str(backup_set_id))

    @staticmethod
    def verify(backup_set_id: uuid.UUID) -> None:
        from app.worker.tasks import verify_backup_set

        verify_backup_set(str(backup_set_id))
