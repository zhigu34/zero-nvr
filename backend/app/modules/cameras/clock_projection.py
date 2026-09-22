from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CameraClockProjection:
    device_id: uuid.UUID
    measured_at: datetime
    health: str
    quality: str
    offset_ms: int | None
    uncertainty_ms: int | None
    rtt_ms: int | None
    device_timezone: str | None
    device_time_source: str | None
    error_code: str | None = None


class CameraClockProjectionStore:
    """Bounded process-local current clock state.

    Clock samples are runtime diagnostics, not durable business facts. Only the
    latest projection per Device is retained, so high-frequency probing never
    creates a database history table.
    """

    def __init__(
        self,
        *,
        max_entries: int = 4096,
    ) -> None:
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._items: OrderedDict[
            uuid.UUID,
            CameraClockProjection,
        ] = OrderedDict()

    def get(
        self,
        device_id: uuid.UUID,
    ) -> CameraClockProjection | None:
        with self._lock:
            return self._items.get(
                device_id
            )

    def put(
        self,
        projection: CameraClockProjection,
    ) -> None:
        with self._lock:
            self._items[
                projection.device_id
            ] = projection
            self._items.move_to_end(
                projection.device_id
            )
            while (
                len(self._items)
                > self._max_entries
            ):
                self._items.popitem(
                    last=False
                )
