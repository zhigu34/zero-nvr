from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ZlmStreamIdentity:
    vhost: str
    app: str
    stream: str


class ZlmContinuityTracker:
    """In-memory proof of one currently observed ZLM stream continuity.

    Missing tracker state means continuity is unproven; callers must keep
    segment timing provisional rather than joining across a possible outage.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[ZlmStreamIdentity, uuid.UUID] = {}

    def registered(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> uuid.UUID:
        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            continuity = self._active.get(identity)
            if continuity is None:
                continuity = uuid.uuid4()
                self._active[identity] = continuity
            return continuity

    def unregistered(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> uuid.UUID | None:
        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            return self._active.pop(identity, None)

    def current(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> uuid.UUID | None:
        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            return self._active.get(identity)
