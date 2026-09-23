from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import select

from app.core.db import Database

from .models import Camera


class RuntimeReconciler:
    """Queue persisted Camera desired state for runtime reconciliation.

    This coordinator intentionally contains no ZLM/ONVIF implementation logic.
    It snapshots canonical Camera identities from the database, closes the
    transaction, then delegates each Camera to the existing runtime task.
    """

    def __init__(
        self,
        database: Database,
        *,
        reconcile_camera: Callable[[uuid.UUID], None],
        reconcile_prebuffer: Callable[
            [uuid.UUID],
            None,
        ] | None = None,
        reconcile_catalog: Callable[
            [],
            None,
        ] | None = None,
    ) -> None:
        self.database = database
        self._reconcile_camera = reconcile_camera
        self._reconcile_prebuffer = reconcile_prebuffer
        self._reconcile_catalog = reconcile_catalog

    def enqueue_all(self) -> int:
        with self.database.session() as session:
            camera_ids = list(
                session.scalars(
                    select(Camera.id).order_by(
                        Camera.id
                    )
                )
            )
            session.commit()

        for camera_id in camera_ids:
            self._reconcile_camera(
                camera_id
            )
            if self._reconcile_prebuffer is not None:
                self._reconcile_prebuffer(
                    camera_id
                )

        if self._reconcile_catalog is not None:
            self._reconcile_catalog()

        return len(camera_ids)
