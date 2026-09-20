from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ZlmStreamIdentity:
    vhost: str
    app: str
    stream: str


@dataclass(slots=True)
class _ActiveContinuity:
    generation: uuid.UUID
    last_segment_id: uuid.UUID | None = None


class ZlmContinuityTracker:
    """In-memory proof of one currently observed ZLM stream continuity.

    Missing tracker state means continuity is unproven; callers must keep
    segment timing provisional rather than joining across a possible outage.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[ZlmStreamIdentity, _ActiveContinuity] = {}

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
                continuity = _ActiveContinuity(generation=uuid.uuid4())
                self._active[identity] = continuity
            return continuity.generation

    def unregistered(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> uuid.UUID | None:
        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            continuity = self._active.pop(identity, None)
            return continuity.generation if continuity is not None else None

    def current(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> uuid.UUID | None:
        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            continuity = self._active.get(identity)
            return continuity.generation if continuity is not None else None


    def last_segment(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> uuid.UUID | None:
        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            continuity = self._active.get(identity)
            if continuity is None:
                return None
            return continuity.last_segment_id

    def remember_segment(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
        segment_id: uuid.UUID,
    ) -> bool:
        """Remember a segment only when continuity is currently proven.

        Returns False when the stream has no active registration proof. In that
        case callers must keep timing provisional and must not create a new
        continuity generation implicitly from a recording hook.
        """

        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            continuity = self._active.get(identity)
            if continuity is None:
                return False
            continuity.last_segment_id = segment_id
            return True
