from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ZlmStreamIdentity:
    vhost: str
    app: str
    stream: str


@dataclass(frozen=True, slots=True)
class ZlmContinuityResolution:
    continuity_id: uuid.UUID
    previous_segment_id: uuid.UUID | None = None
    closed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _ContinuityState:
    continuity_id: uuid.UUID
    registered_at: datetime
    last_segment_id: uuid.UUID | None = None
    closed_at: datetime | None = None


class ZlmContinuityTracker:
    """In-memory proof of observed ZLM stream continuity.

    One recently closed generation is retained per stream so a finalized MP4
    hook that arrives just after unregister/reconnect can still be assigned to
    the old continuity rather than the new one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[ZlmStreamIdentity, _ContinuityState] = {}
        self._closed: dict[ZlmStreamIdentity, _ContinuityState] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def registered(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
        at: datetime | None = None,
    ) -> uuid.UUID:
        identity = ZlmStreamIdentity(vhost, app, stream)
        registered_at = at or self._now()
        with self._lock:
            active = self._active.get(identity)
            if active is not None:
                return active.continuity_id

            state = _ContinuityState(
                continuity_id=uuid.uuid4(),
                registered_at=registered_at,
            )
            self._active[identity] = state
            return state.continuity_id

    def unregistered(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
        at: datetime | None = None,
    ) -> uuid.UUID | None:
        identity = ZlmStreamIdentity(vhost, app, stream)
        closed_at = at or self._now()
        with self._lock:
            active = self._active.pop(identity, None)
            if active is None:
                return None

            closed = _ContinuityState(
                continuity_id=active.continuity_id,
                registered_at=active.registered_at,
                last_segment_id=active.last_segment_id,
                closed_at=closed_at,
            )
            self._closed[identity] = closed
            return closed.continuity_id

    def closed_resolution(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> ZlmContinuityResolution | None:
        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            state = self._closed.get(identity)
            if state is None or state.closed_at is None:
                return None
            return ZlmContinuityResolution(
                continuity_id=state.continuity_id,
                previous_segment_id=state.last_segment_id,
                closed_at=state.closed_at,
            )

    def active_resolution(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> ZlmContinuityResolution | None:
        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            state = self._active.get(identity)
            if state is None:
                return None
            return ZlmContinuityResolution(
                continuity_id=state.continuity_id,
                previous_segment_id=state.last_segment_id,
            )

    def current(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
    ) -> uuid.UUID | None:
        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            state = self._active.get(identity)
            return state.continuity_id if state else None

    def resolve_record(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
        started_at: datetime,
    ) -> ZlmContinuityResolution | None:
        """Resolve a record hook to an active or just-closed generation."""

        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            active = self._active.get(identity)
            closed = self._closed.get(identity)

            # A late old-generation MP4 hook has a file-creation/start evidence
            # before the old unregister boundary and before a newer register.
            if (
                closed is not None
                and closed.closed_at is not None
                and started_at <= closed.closed_at
                and (
                    active is None
                    or started_at < active.registered_at
                )
            ):
                return ZlmContinuityResolution(
                    continuity_id=closed.continuity_id,
                    previous_segment_id=closed.last_segment_id,
                    closed_at=closed.closed_at,
                )

            if active is not None and started_at >= active.registered_at:
                return ZlmContinuityResolution(
                    continuity_id=active.continuity_id,
                    previous_segment_id=active.last_segment_id,
                )

            return None


    def remember_segment(
        self,
        *,
        vhost: str,
        app: str,
        stream: str,
        continuity_id: uuid.UUID,
        segment_id: uuid.UUID,
    ) -> bool:
        """Remember one finalized catalog segment in a proven generation.

        The generation id is runtime-only proof. It is never persisted on the
        RecordingSegment row. A late hook can update the retained closed
        generation without contaminating a newly active generation.
        """

        identity = ZlmStreamIdentity(vhost, app, stream)
        with self._lock:
            active = self._active.get(identity)
            if (
                active is not None
                and active.continuity_id == continuity_id
            ):
                self._active[identity] = _ContinuityState(
                    continuity_id=active.continuity_id,
                    registered_at=active.registered_at,
                    last_segment_id=segment_id,
                    closed_at=active.closed_at,
                )
                return True

            closed = self._closed.get(identity)
            if (
                closed is not None
                and closed.continuity_id == continuity_id
            ):
                self._closed[identity] = _ContinuityState(
                    continuity_id=closed.continuity_id,
                    registered_at=closed.registered_at,
                    last_segment_id=segment_id,
                    closed_at=closed.closed_at,
                )
                return True

            return False
