from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any


class RuntimeEventBus:
    """Process-local SSE hint fanout.

    Hints are intentionally non-canonical. Slow subscribers may drop old hints
    and must refetch durable API state.
    """

    def __init__(
        self,
        *,
        queue_size: int = 64,
    ) -> None:
        if queue_size < 4 or queue_size > 1024:
            raise ValueError("runtime event queue size is invalid")
        self._queue_size = queue_size
        self._lock = asyncio.Lock()
        self._subscribers: set[
            asyncio.Queue[dict[str, Any]]
        ] = set()
        self._sequence = 0

    async def subscribe(
        self,
    ) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue(
                maxsize=self._queue_size
            )
        )
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(
        self,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        async with self._lock:
            self._sequence += 1
            event = {
                "id": self._sequence,
                "type": event_type,
                "at": datetime.now(UTC).isoformat(),
                "data": data,
            }
            subscribers = tuple(
                self._subscribers
            )

        for queue in subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A hint can be lost safely because clients refetch canonical
                # data after any received hint.
                pass
