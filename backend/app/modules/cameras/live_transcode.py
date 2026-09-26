from __future__ import annotations

import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.core.config import Settings
from app.core.db import Database
from app.integrations.zlm import (
    ZlmAdapter,
    ZlmIntegrationError,
)
from app.modules.system.settings import (
    RuntimeTuningSettings,
    RuntimeTuningSettingsService,
)

from .media_runtime import ZlmStreamReference


class LiveTranscodeError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 503,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class LiveTranscodeLease:
    lease_id: uuid.UUID
    reference: ZlmStreamReference
    acceleration: str


@dataclass(slots=True)
class _LeaseState:
    camera_id: uuid.UUID
    owner_user_id: uuid.UUID
    key: str
    timer: Any | None = None


@dataclass(slots=True)
class _DerivativeState:
    reference: ZlmStreamReference
    process: Any
    acceleration: str
    leases: set[uuid.UUID] = field(
        default_factory=set
    )
    idle_timer: Any | None = None


class LiveTranscodeManager:
    app_name = "zero-nvr-compat"

    def __init__(
        self,
        settings: Settings,
        *,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        run_factory: Callable[..., Any] = subprocess.run,
        zlm_factory: Callable[[Settings], Any] = ZlmAdapter,
        timer_factory: Callable[..., Any] = threading.Timer,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        path_exists: Callable[[str], bool] | None = None,
        database: Database | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self._popen_factory = popen_factory
        self._run_factory = run_factory
        self._zlm_factory = zlm_factory
        self._timer_factory = timer_factory
        self._sleep = sleep
        self._monotonic = monotonic
        self._path_exists = (
            path_exists
            if path_exists is not None
            else lambda value: Path(value).exists()
        )
        self._lock = threading.RLock()
        self._derivatives: dict[
            str,
            _DerivativeState,
        ] = {}
        self._leases: dict[
            uuid.UUID,
            _LeaseState,
        ] = {}
        self._acceleration: str | None = None

    def _tuning(self) -> RuntimeTuningSettings:
        if self.database is None:
            return RuntimeTuningSettingsService.defaults(
                self.settings
            )
        with self.database.session() as session:
            return RuntimeTuningSettingsService.get(
                session,
                settings=self.settings,
            )

    @staticmethod
    def _key(profile_id: uuid.UUID) -> str:
        return f"h264:{profile_id}"

    @classmethod
    def _reference(
        cls,
        *,
        camera_id: uuid.UUID,
        profile_id: uuid.UUID,
    ) -> ZlmStreamReference:
        return ZlmStreamReference(
            camera_id=camera_id,
            profile_id=profile_id,
            app=cls.app_name,
            stream=f"h264-{profile_id.hex}",
        )

    def acceleration(self) -> str:
        with self._lock:
            if self._acceleration is None:
                self._acceleration = (
                    self._probe_acceleration()
                )
            return self._acceleration

    def _probe_acceleration(self) -> str:
        try:
            completed = self._run_factory(
                [
                    self.settings.ffmpeg_binary,
                    "-hide_banner",
                    "-encoders",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            output = (
                str(getattr(completed, "stdout", ""))
                + str(getattr(completed, "stderr", ""))
            )
        except (OSError, subprocess.SubprocessError):
            return "cpu"

        if (
            self._path_exists("/dev/nvidia0")
            and "h264_nvenc" in output
        ):
            return "nvenc"
        if (
            self._path_exists("/dev/dri/renderD128")
            and "h264_vaapi" in output
        ):
            return "vaapi"
        return "cpu"

    def _ffmpeg_command(
        self,
        *,
        source_url: str,
        destination_url: str,
        has_audio: bool,
        acceleration: str,
    ) -> list[str]:
        tuning = self._tuning()
        bitrate = (
            tuning.live_transcode_video_bitrate_kbps
        )
        command = [
            self.settings.ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            "tcp",
            "-i",
            source_url,
            "-map",
            "0:v:0",
        ]

        if acceleration == "nvenc":
            command.extend(
                [
                    "-c:v",
                    "h264_nvenc",
                    "-preset",
                    "p4",
                    "-tune",
                    "ll",
                    "-rc",
                    "vbr",
                ]
            )
        elif acceleration == "vaapi":
            command.extend(
                [
                    "-vaapi_device",
                    "/dev/dri/renderD128",
                    "-vf",
                    "format=nv12,hwupload",
                    "-c:v",
                    "h264_vaapi",
                ]
            )
        else:
            command.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-tune",
                    "zerolatency",
                    "-threads",
                    str(
                        tuning
                        .live_transcode_cpu_threads
                    ),
                    "-profile:v",
                    "main",
                    "-pix_fmt",
                    "yuv420p",
                ]
            )

        command.extend(
            [
                "-b:v",
                f"{bitrate}k",
                "-maxrate",
                f"{bitrate}k",
                "-bufsize",
                f"{bitrate * 2}k",
                "-g",
                "50",
                "-keyint_min",
                "50",
                "-sc_threshold",
                "0",
            ]
        )
        if has_audio:
            command.extend(
                [
                    "-map",
                    "0:a:0?",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "64k",
                    "-ar",
                    "48000",
                ]
            )
        else:
            command.append("-an")

        command.extend(
            [
                "-f",
                "flv",
                destination_url,
            ]
        )
        return command

    def _spawn(
        self,
        *,
        source_url: str,
        reference: ZlmStreamReference,
        has_audio: bool,
        acceleration: str,
    ) -> Any:
        destination = (
            self.settings.zlm_rtmp_base_url.rstrip("/")
            + f"/{reference.app}/{reference.stream}"
        )
        command = self._ffmpeg_command(
            source_url=source_url,
            destination_url=destination,
            has_audio=has_audio,
            acceleration=acceleration,
        )
        try:
            return self._popen_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            raise LiveTranscodeError(
                "live_transcode_spawn_failed",
                "Compatibility transcode could not be started.",
            ) from exc

    def _wait_online(
        self,
        *,
        process: Any,
        reference: ZlmStreamReference,
    ) -> bool:
        deadline = (
            self._monotonic()
            + self._tuning()
            .live_transcode_startup_timeout_seconds
        )
        try:
            with self._zlm_factory(
                self.settings
            ) as zlm:
                while self._monotonic() < deadline:
                    if process.poll() is not None:
                        return False
                    try:
                        if zlm.is_media_online(
                            app=reference.app,
                            stream=reference.stream,
                            schema="hls",
                        ):
                            return True
                    except ZlmIntegrationError:
                        pass
                    self._sleep(0.2)
        except ZlmIntegrationError:
            return False
        return False

    @staticmethod
    def _stop_process(process: Any) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:
                pass

    def _start_derivative(
        self,
        *,
        source_url: str,
        reference: ZlmStreamReference,
        has_audio: bool,
    ) -> _DerivativeState:
        preferred = self.acceleration()
        attempts = (
            [preferred, "cpu"]
            if preferred != "cpu"
            else ["cpu"]
        )

        for acceleration in attempts:
            process = self._spawn(
                source_url=source_url,
                reference=reference,
                has_audio=has_audio,
                acceleration=acceleration,
            )
            if self._wait_online(
                process=process,
                reference=reference,
            ):
                return _DerivativeState(
                    reference=reference,
                    process=process,
                    acceleration=acceleration,
                )
            self._stop_process(process)

        raise LiveTranscodeError(
            "live_transcode_start_failed",
            "Compatibility transcode did not become ready.",
            status_code=502,
        )

    def _make_timer(
        self,
        seconds: float,
        callback: Callable[..., None],
        *args: object,
    ) -> Any:
        timer = self._timer_factory(
            seconds,
            callback,
            args=args,
        )
        if hasattr(timer, "daemon"):
            timer.daemon = True
        timer.start()
        return timer

    def _cancel_timer(
        self,
        timer: Any | None,
    ) -> None:
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _schedule_lease_expiry_locked(
        self,
        lease_id: uuid.UUID,
    ) -> None:
        lease = self._leases.get(lease_id)
        if lease is None:
            return
        self._cancel_timer(lease.timer)
        lease.timer = self._make_timer(
            self._tuning()
            .live_transcode_lease_ttl_seconds,
            self._expire_lease,
            lease_id,
        )

    def _schedule_idle_locked(
        self,
        key: str,
        entry: _DerivativeState,
    ) -> None:
        self._cancel_timer(entry.idle_timer)
        entry.idle_timer = self._make_timer(
            self._tuning()
            .live_transcode_idle_ttl_seconds,
            self._expire_derivative,
            key,
        )

    def _drop_entry_locked(
        self,
        key: str,
    ) -> _DerivativeState | None:
        entry = self._derivatives.pop(
            key,
            None,
        )
        if entry is None:
            return None

        self._cancel_timer(entry.idle_timer)
        entry.idle_timer = None
        for lease_id in list(entry.leases):
            lease = self._leases.pop(
                lease_id,
                None,
            )
            if lease is not None:
                self._cancel_timer(
                    lease.timer
                )
        entry.leases.clear()
        return entry

    def _expire_lease(
        self,
        lease_id: uuid.UUID,
    ) -> None:
        self.release(lease_id)

    def _expire_derivative(
        self,
        key: str,
    ) -> None:
        with self._lock:
            entry = self._derivatives.get(key)
            if (
                entry is None
                or entry.leases
            ):
                return
            removed = self._drop_entry_locked(
                key
            )
        if removed is not None:
            self._stop_process(
                removed.process
            )

    def _free_idle_capacity_locked(
        self,
    ) -> None:
        # Exited processes cannot serve any of their viewers. Reap them
        # before counting capacity, even when their leases are still alive.
        for key, entry in list(self._derivatives.items()):
            if entry.process.poll() is not None:
                self._drop_entry_locked(key)

        if (
            len(self._derivatives)
            < self._tuning()
            .live_transcode_max_derivatives
        ):
            return

        idle_keys = [
            key
            for key, entry in self._derivatives.items()
            if not entry.leases
        ]
        for key in idle_keys:
            removed = self._drop_entry_locked(
                key
            )
            if removed is not None:
                self._stop_process(
                    removed.process
                )
            if (
                len(self._derivatives)
                < self._tuning()
                .live_transcode_max_derivatives
            ):
                return

    def acquire(
        self,
        *,
        camera_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        profile_id: uuid.UUID,
        source_url: str,
        has_audio: bool,
    ) -> LiveTranscodeLease:
        key = self._key(profile_id)
        reference = self._reference(
            camera_id=camera_id,
            profile_id=profile_id,
        )

        with self._lock:
            entry = self._derivatives.get(
                key
            )
            if (
                entry is not None
                and entry.process.poll()
                is not None
            ):
                stale = self._drop_entry_locked(
                    key
                )
                if stale is not None:
                    self._stop_process(
                        stale.process
                    )
                entry = None

            if entry is None:
                self._free_idle_capacity_locked()
                tuning = self._tuning()
                if (
                    len(self._derivatives)
                    >= tuning.live_transcode_max_derivatives
                ):
                    active_leases = len(self._leases)
                    raise LiveTranscodeError(
                        "live_transcode_capacity",
                        (
                            "Compatibility transcode capacity is exhausted "
                            f"({len(self._derivatives)}/"
                            f"{tuning.live_transcode_max_derivatives} "
                            f"derivatives, {active_leases} active leases)."
                        ),
                        status_code=503,
                    )
                entry = self._start_derivative(
                    source_url=source_url,
                    reference=reference,
                    has_audio=has_audio,
                )
                self._derivatives[key] = entry

            self._cancel_timer(
                entry.idle_timer
            )
            entry.idle_timer = None

            lease_id = uuid.uuid4()
            entry.leases.add(lease_id)
            self._leases[lease_id] = (
                _LeaseState(
                    camera_id=camera_id,
                    owner_user_id=owner_user_id,
                    key=key,
                )
            )
            self._schedule_lease_expiry_locked(
                lease_id
            )

            return LiveTranscodeLease(
                lease_id=lease_id,
                reference=entry.reference,
                acceleration=entry.acceleration,
            )

    def touch(
        self,
        lease_id: uuid.UUID,
        *,
        camera_id: uuid.UUID,
        owner_user_id: uuid.UUID,
    ) -> bool:
        with self._lock:
            lease = self._leases.get(
                lease_id
            )
            if (
                lease is None
                or lease.camera_id
                != camera_id
                or lease.owner_user_id
                != owner_user_id
            ):
                return False
            entry = self._derivatives.get(lease.key)
            if entry is None or entry.process.poll() is not None:
                self._drop_entry_locked(lease.key)
                return False
            self._schedule_lease_expiry_locked(
                lease_id
            )
            return True

    def release(
        self,
        lease_id: uuid.UUID,
        *,
        camera_id: uuid.UUID | None = None,
        owner_user_id: uuid.UUID | None = None,
    ) -> bool:
        with self._lock:
            lease = self._leases.get(
                lease_id
            )
            if lease is None:
                return False
            if (
                camera_id is not None
                and lease.camera_id
                != camera_id
            ):
                return False
            if (
                owner_user_id is not None
                and lease.owner_user_id
                != owner_user_id
            ):
                return False

            self._leases.pop(
                lease_id,
                None,
            )
            self._cancel_timer(
                lease.timer
            )
            entry = self._derivatives.get(
                lease.key
            )
            if entry is None:
                return True

            entry.leases.discard(
                lease_id
            )
            if not entry.leases:
                self._schedule_idle_locked(
                    lease.key,
                    entry,
                )
            return True

    def stop(self) -> None:
        with self._lock:
            entries = list(
                self._derivatives.values()
            )
            for lease in self._leases.values():
                self._cancel_timer(
                    lease.timer
                )
            for entry in entries:
                self._cancel_timer(
                    entry.idle_timer
                )
            self._leases.clear()
            self._derivatives.clear()

        for entry in entries:
            self._stop_process(
                entry.process
            )
