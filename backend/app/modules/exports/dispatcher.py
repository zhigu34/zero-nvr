from __future__ import annotations

import uuid


class ExportTaskDispatcher:
    @staticmethod
    def render(export_id: uuid.UUID) -> None:
        from app.worker.tasks import render_export

        render_export(str(export_id))

    @staticmethod
    def expire() -> None:
        from app.worker.tasks import expire_exports

        expire_exports()
