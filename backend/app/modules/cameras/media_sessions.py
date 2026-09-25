from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


Cleanup = Callable[[], None]


@dataclass(slots=True)
class _MediaSession:
    owner_user_id: uuid.UUID
    camera_id: uuid.UUID
    profile_id: uuid.UUID | None = None
    purpose: str | None = None
    cleanups: dict[str, Cleanup] = field(
        default_factory=dict
    )
    timer: Any | None = None
    generation: int = 0


class MediaSessionRegistry:
    """In-memory live media-session authority.

    Sessions are intentionally ephemeral. An API restart invalidates every
    outstanding live grant, which is safer than persisting bearer capability
    state and matches the frontend's reconnect/re-resolve behavior.
    """

    def __init__(
        self,
        *,
        timer_factory: Callable[..., Any] = threading.Timer,
    ) -> None:
        self._timer_factory = timer_factory
        self._lock = threading.RLock()
        self._sessions: dict[
            uuid.UUID,
            _MediaSession,
        ] = {}

    def issue(
        self,
        *,
        owner_user_id: uuid.UUID,
        camera_id: uuid.UUID,
        ttl_seconds: int,
        profile_id: uuid.UUID | None = None,
        purpose: str | None = None,
    ) -> uuid.UUID:
        if ttl_seconds <= 0:
            raise ValueError(
                "media session TTL must be positive"
            )

        session_id = uuid.uuid4()
        state = _MediaSession(
            owner_user_id=owner_user_id,
            camera_id=camera_id,
            profile_id=profile_id,
            purpose=purpose,
        )
        timer = self._timer_factory(
            ttl_seconds,
            self._expire,
            args=(
                session_id,
                state.generation,
            ),
        )
        if hasattr(timer, "daemon"):
            timer.daemon = True
        state.timer = timer

        with self._lock:
            self._sessions[session_id] = state
        timer.start()
        return session_id

    def authorize(
        self,
        session_id: uuid.UUID,
        *,
        owner_user_id: uuid.UUID,
        camera_id: uuid.UUID,
    ) -> bool:
        with self._lock:
            state = self._sessions.get(
                session_id
            )
            return bool(
                state is not None
                and state.owner_user_id
                == owner_user_id
                and state.camera_id
                == camera_id
            )

    def stream_context(
        self,
        session_id: uuid.UUID,
        *,
        owner_user_id: uuid.UUID,
        camera_id: uuid.UUID,
    ) -> tuple[uuid.UUID, str] | None:
        with self._lock:
            state = self._sessions.get(session_id)
            if (
                state is None
                or state.owner_user_id != owner_user_id
                or state.camera_id != camera_id
                or state.profile_id is None
                or state.purpose is None
            ):
                return None
            return state.profile_id, state.purpose

    def active(
        self,
        session_id: uuid.UUID,
    ) -> bool:
        with self._lock:
            return session_id in self._sessions

    def renew(
        self,
        session_id: uuid.UUID,
        *,
        owner_user_id: uuid.UUID,
        camera_id: uuid.UUID,
        ttl_seconds: int,
    ) -> bool:
        if ttl_seconds <= 0:
            raise ValueError(
                "media session TTL must be positive"
            )

        with self._lock:
            state = self._sessions.get(
                session_id
            )
            if (
                state is None
                or state.owner_user_id
                != owner_user_id
                or state.camera_id
                != camera_id
            ):
                return False

            previous_timer = state.timer
            state.generation += 1
            timer = self._timer_factory(
                ttl_seconds,
                self._expire,
                args=(
                    session_id,
                    state.generation,
                ),
            )
            if hasattr(timer, "daemon"):
                timer.daemon = True
            state.timer = timer
            self._cancel_timer(
                previous_timer
            )
            timer.start()
            return True

    def register_cleanup(
        self,
        session_id: uuid.UUID,
        *,
        key: str,
        cleanup: Cleanup,
    ) -> bool:
        with self._lock:
            state = self._sessions.get(
                session_id
            )
            if state is None:
                return False
            state.cleanups[key] = cleanup
            return True

    def unregister_cleanup(
        self,
        session_id: uuid.UUID,
        *,
        key: str,
    ) -> None:
        with self._lock:
            state = self._sessions.get(
                session_id
            )
            if state is not None:
                state.cleanups.pop(
                    key,
                    None,
                )

    @staticmethod
    def _cancel_timer(
        timer: Any | None,
    ) -> None:
        if timer is None:
            return
        try:
            timer.cancel()
        except Exception:
            pass

    @staticmethod
    def _run_cleanups(
        cleanups: list[Cleanup],
    ) -> None:
        for cleanup in cleanups:
            try:
                cleanup()
            except Exception:
                # Revocation is best-effort for transport cleanup. Removing
                # the session authority itself is the security boundary.
                pass

    def revoke(
        self,
        session_id: uuid.UUID,
        *,
        owner_user_id: uuid.UUID | None = None,
        camera_id: uuid.UUID | None = None,
    ) -> bool:
        with self._lock:
            state = self._sessions.get(
                session_id
            )
            if state is None:
                return False
            if (
                owner_user_id is not None
                and state.owner_user_id
                != owner_user_id
            ):
                return False
            if (
                camera_id is not None
                and state.camera_id
                != camera_id
            ):
                return False

            self._sessions.pop(
                session_id,
                None,
            )
            self._cancel_timer(
                state.timer
            )
            cleanups = list(
                state.cleanups.values()
            )
            state.cleanups.clear()

        self._run_cleanups(cleanups)
        return True

    def _expire(
        self,
        session_id: uuid.UUID,
        generation: int,
    ) -> None:
        with self._lock:
            state = self._sessions.get(
                session_id
            )
            if (
                state is None
                or state.generation
                != generation
            ):
                return
            self._sessions.pop(
                session_id,
                None,
            )
            cleanups = list(
                state.cleanups.values()
            )
            state.cleanups.clear()

        self._run_cleanups(cleanups)

    def stop(self) -> None:
        with self._lock:
            session_ids = list(
                self._sessions
            )
        for session_id in session_ids:
            self.revoke(session_id)
