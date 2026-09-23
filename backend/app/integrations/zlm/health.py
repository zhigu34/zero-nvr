from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ZlmMediaHealthObservation:
    profile_id: uuid.UUID
    online: bool
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ZlmRecordingHealthObservation:
    profile_id: uuid.UUID
    finalized_at: datetime


class ZlmObservedHealthStore:
    """Current process-local ZLM media/recorder observations.

    ZLM hooks are runtime evidence, not durable business facts. Only the latest
    registration state and latest accepted finalized MP4 evidence per stream
    profile are retained.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._media: dict[
            uuid.UUID,
            ZlmMediaHealthObservation,
        ] = {}
        self._recording: dict[
            uuid.UUID,
            ZlmRecordingHealthObservation,
        ] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def stream_registered(
        self,
        profile_id: uuid.UUID,
        *,
        at: datetime | None = None,
    ) -> None:
        observed_at = at or self._now()
        with self._lock:
            self._media[
                profile_id
            ] = ZlmMediaHealthObservation(
                profile_id=profile_id,
                online=True,
                observed_at=observed_at,
            )

    def stream_unregistered(
        self,
        profile_id: uuid.UUID,
        *,
        at: datetime | None = None,
    ) -> None:
        observed_at = at or self._now()
        with self._lock:
            self._media[
                profile_id
            ] = ZlmMediaHealthObservation(
                profile_id=profile_id,
                online=False,
                observed_at=observed_at,
            )

    def recording_finalized(
        self,
        profile_id: uuid.UUID,
        *,
        at: datetime | None = None,
    ) -> None:
        finalized_at = at or self._now()
        with self._lock:
            self._recording[
                profile_id
            ] = ZlmRecordingHealthObservation(
                profile_id=profile_id,
                finalized_at=finalized_at,
            )

    def media(
        self,
        profile_id: uuid.UUID,
    ) -> ZlmMediaHealthObservation | None:
        with self._lock:
            return self._media.get(
                profile_id
            )

    def recording(
        self,
        profile_id: uuid.UUID,
    ) -> ZlmRecordingHealthObservation | None:
        with self._lock:
            return self._recording.get(
                profile_id
            )
