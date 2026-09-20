from __future__ import annotations

import uuid
from collections.abc import Callable


class NotificationTaskDispatcher:
    """Queue boundary for notification delivery work."""

    def __init__(
        self,
        *,
        enqueue: Callable[[str], object] | None = None,
    ) -> None:
        self._enqueue = enqueue

    def deliver(
        self,
        delivery_id: uuid.UUID,
    ) -> None:
        enqueue = self._enqueue
        if enqueue is None:
            from app.worker.tasks import deliver_notification

            enqueue = deliver_notification
        enqueue(str(delivery_id))

    def deliver_many(
        self,
        delivery_ids: tuple[uuid.UUID, ...] | list[uuid.UUID],
    ) -> None:
        for delivery_id in delivery_ids:
            self.deliver(delivery_id)
