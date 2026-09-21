from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError

from .models import (
    Camera,
    CameraStreamProfile,
    Device,
)
from .service import CameraService


@dataclass(frozen=True, slots=True)
class CameraTalkConnection:
    camera_id: uuid.UUID
    profile_id: uuid.UUID
    profile_token: str
    audio_codec: str | None
    source_uri: str = field(repr=False)


class CameraTalkService:
    """Resolve evidence-backed ONVIF talk capability server-side."""

    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self.settings = settings
        self._cameras = CameraService(
            settings
        )

    @staticmethod
    def _profile_capable(
        profile: CameraStreamProfile,
    ) -> bool:
        metadata = (
            profile.metadata_json
            if isinstance(
                profile.metadata_json,
                dict,
            )
            else {}
        )
        return (
            profile.stream_uri_ref
            is not None
            and metadata.get(
                "onvif_audio_backchannel"
            )
            is True
        )

    @classmethod
    def is_capable(
        cls,
        session: Session,
        camera: Camera,
    ) -> bool:
        if (
            camera.retired_at is not None
            or not camera.enabled
            or camera.device_id is None
        ):
            return False
        device = session.get(
            Device,
            camera.device_id,
        )
        if (
            device is None
            or not device.enabled
            or device.adapter_type != "onvif"
        ):
            return False
        return any(
            cls._profile_capable(profile)
            for profile
            in camera.stream_profiles
        )

    def connection(
        self,
        session: Session,
        camera: Camera,
    ) -> CameraTalkConnection:
        if not self.is_capable(
            session,
            camera,
        ):
            raise ApiError(
                status_code=409,
                code="camera_talk_unavailable",
                message=(
                    "Camera does not advertise "
                    "a supported ONVIF audio "
                    "backchannel."
                ),
            )

        by_id = {
            profile.id: profile
            for profile
            in camera.stream_profiles
        }
        bindings = {
            binding.purpose:
                binding.stream_profile_id
            for binding
            in camera.stream_bindings
        }

        ordered: list[
            CameraStreamProfile
        ] = []
        for purpose in (
            "AUDIO",
            "LIVE_HIGH",
            "RECORD",
            "LIVE_LOW",
        ):
            profile_id = bindings.get(
                purpose
            )
            profile = (
                by_id.get(profile_id)
                if profile_id is not None
                else None
            )
            if (
                profile is not None
                and profile not in ordered
            ):
                ordered.append(profile)
        ordered.extend(
            profile
            for profile
            in camera.stream_profiles
            if profile not in ordered
        )

        profile = next(
            (
                item
                for item in ordered
                if self._profile_capable(
                    item
                )
            ),
            None,
        )
        if profile is None:
            raise ApiError(
                status_code=409,
                code="camera_talk_unavailable",
                message=(
                    "Camera talk profile is "
                    "unavailable."
                ),
            )

        return CameraTalkConnection(
            camera_id=camera.id,
            profile_id=profile.id,
            profile_token=(
                profile.adapter_profile_key
            ),
            audio_codec=(
                profile.audio_codec
            ),
            source_uri=(
                self._cameras
                .resolve_stream_uri(
                    session,
                    profile,
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class TalkBackendHandle:
    descriptor: dict[str, Any]
    state: Any = field(
        default=None,
        repr=False,
    )


class TalkBackend(Protocol):
    name: str
    modes: tuple[str, ...]

    def available(self) -> bool:
        ...

    def supports(
        self,
        connection: CameraTalkConnection,
    ) -> bool:
        ...

    def start(
        self,
        *,
        talk_session_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        connection: CameraTalkConnection,
        mode: str,
    ) -> TalkBackendHandle:
        ...

    def stop(
        self,
        handle: TalkBackendHandle,
    ) -> None:
        ...


class UnsupportedTalkBackend:
    name = "unavailable"
    modes: tuple[str, ...] = ()

    def available(self) -> bool:
        return False

    def supports(
        self,
        connection: CameraTalkConnection,
    ) -> bool:
        return False

    def start(
        self,
        *,
        talk_session_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        connection: CameraTalkConnection,
        mode: str,
    ) -> TalkBackendHandle:
        raise RuntimeError(
            "Talk backend is unavailable."
        )

    def stop(
        self,
        handle: TalkBackendHandle,
    ) -> None:
        return None


class TalkSessionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class TalkSessionLease:
    id: uuid.UUID
    camera_id: uuid.UUID
    owner_user_id: uuid.UUID
    backend: str
    mode: str
    descriptor: dict[str, Any]


@dataclass(slots=True)
class _TalkSessionState:
    camera_id: uuid.UUID
    owner_user_id: uuid.UUID
    backend: TalkBackend
    mode: str
    handle: TalkBackendHandle | None
    timer: Any | None = None


class TalkSessionManager:
    """Ephemeral one-active-talker-per-camera lease manager."""

    def __init__(
        self,
        *,
        timer_factory: Callable[..., Any]
        = threading.Timer,
    ) -> None:
        self._timer_factory = (
            timer_factory
        )
        self._lock = threading.RLock()
        self._sessions: dict[
            uuid.UUID,
            _TalkSessionState,
        ] = {}
        self._camera_sessions: dict[
            uuid.UUID,
            uuid.UUID,
        ] = {}

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

    def _schedule_locked(
        self,
        session_id: uuid.UUID,
        ttl_seconds: int,
    ) -> None:
        state = self._sessions.get(
            session_id
        )
        if state is None:
            return
        self._cancel_timer(
            state.timer
        )
        timer = self._timer_factory(
            ttl_seconds,
            self._expire,
            args=(session_id,),
        )
        if hasattr(
            timer,
            "daemon",
        ):
            timer.daemon = True
        state.timer = timer
        timer.start()

    def start(
        self,
        *,
        camera_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        connection: CameraTalkConnection,
        backend: TalkBackend,
        mode: str,
        ttl_seconds: int = 30,
    ) -> TalkSessionLease:
        if ttl_seconds <= 0:
            raise ValueError(
                "talk session TTL must "
                "be positive"
            )
        if not backend.available():
            raise TalkSessionError(
                "camera_talk_backend_unavailable",
                "Talk backend is unavailable.",
            )
        if mode not in backend.modes:
            raise TalkSessionError(
                "camera_talk_mode_unavailable",
                "Requested talk mode is "
                "not supported.",
                status_code=400,
            )
        if not backend.supports(
            connection
        ):
            raise TalkSessionError(
                "camera_talk_backend_unavailable",
                "Talk backend cannot handle "
                "this camera profile.",
            )

        talk_session_id = uuid.uuid4()
        with self._lock:
            existing = (
                self._camera_sessions.get(
                    camera_id
                )
            )
            if existing is not None:
                raise TalkSessionError(
                    "camera_talk_busy",
                    "Another talk session is "
                    "already active for this "
                    "camera.",
                )
            state = _TalkSessionState(
                camera_id=camera_id,
                owner_user_id=(
                    owner_user_id
                ),
                backend=backend,
                mode=mode,
                handle=None,
            )
            self._sessions[
                talk_session_id
            ] = state
            self._camera_sessions[
                camera_id
            ] = talk_session_id

        try:
            handle = backend.start(
                talk_session_id=(
                    talk_session_id
                ),
                owner_user_id=(
                    owner_user_id
                ),
                connection=connection,
                mode=mode,
            )
        except Exception as exc:
            with self._lock:
                self._sessions.pop(
                    talk_session_id,
                    None,
                )
                if (
                    self._camera_sessions
                    .get(camera_id)
                    == talk_session_id
                ):
                    self._camera_sessions.pop(
                        camera_id,
                        None,
                    )
            if isinstance(
                exc,
                TalkSessionError,
            ):
                raise
            raise TalkSessionError(
                "camera_talk_start_failed",
                "Talk backend could not "
                "start the session.",
                status_code=502,
            ) from exc

        with self._lock:
            current = self._sessions.get(
                talk_session_id
            )
            if current is None:
                try:
                    backend.stop(handle)
                except Exception:
                    pass
                raise TalkSessionError(
                    "camera_talk_start_failed",
                    "Talk session was "
                    "cancelled during startup.",
                )
            current.handle = handle
            self._schedule_locked(
                talk_session_id,
                ttl_seconds,
            )

        return TalkSessionLease(
            id=talk_session_id,
            camera_id=camera_id,
            owner_user_id=(
                owner_user_id
            ),
            backend=backend.name,
            mode=mode,
            descriptor=dict(
                handle.descriptor
            ),
        )

    def touch(
        self,
        talk_session_id: uuid.UUID,
        *,
        camera_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        ttl_seconds: int = 30,
    ) -> bool:
        with self._lock:
            state = self._sessions.get(
                talk_session_id
            )
            if (
                state is None
                or state.camera_id
                != camera_id
                or state.owner_user_id
                != owner_user_id
            ):
                return False
            self._schedule_locked(
                talk_session_id,
                ttl_seconds,
            )
            return True

    def stop(
        self,
        talk_session_id: uuid.UUID,
        *,
        camera_id: uuid.UUID | None
        = None,
        owner_user_id: uuid.UUID
        | None = None,
    ) -> bool:
        with self._lock:
            state = self._sessions.get(
                talk_session_id
            )
            if state is None:
                return False
            if (
                camera_id is not None
                and state.camera_id
                != camera_id
            ):
                return False
            if (
                owner_user_id is not None
                and state.owner_user_id
                != owner_user_id
            ):
                return False

            self._sessions.pop(
                talk_session_id,
                None,
            )
            if (
                self._camera_sessions.get(
                    state.camera_id
                )
                == talk_session_id
            ):
                self._camera_sessions.pop(
                    state.camera_id,
                    None,
                )
            self._cancel_timer(
                state.timer
            )
            handle = state.handle

        if handle is not None:
            try:
                state.backend.stop(
                    handle
                )
            except Exception:
                pass
        return True

    def _expire(
        self,
        talk_session_id: uuid.UUID,
    ) -> None:
        self.stop(
            talk_session_id
        )

    def active_for_camera(
        self,
        camera_id: uuid.UUID,
    ) -> bool:
        with self._lock:
            return (
                camera_id
                in self._camera_sessions
            )

    def stop_all(self) -> None:
        with self._lock:
            ids = list(
                self._sessions
            )
        for talk_session_id in ids:
            self.stop(
                talk_session_id
            )
