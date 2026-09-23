from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.recordings.arbiter import (
    RecordingArbiterService,
)
from app.modules.recordings.models import RecordingPolicy

from .models import (
    Camera,
    Device,
    DeviceEndpoint,
)


@dataclass(frozen=True, slots=True)
class CapabilityHealthLayer:
    state: str
    reason: str | None = None
    details: dict[str, object] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class CameraCapabilityHealth:
    camera_id: uuid.UUID
    control: CapabilityHealthLayer
    media: CapabilityHealthLayer
    recording: CapabilityHealthLayer
    events: CapabilityHealthLayer
    ptz: CapabilityHealthLayer
    clock: CapabilityHealthLayer


class CameraCapabilityHealthService:
    """Project independent Camera capability health layers.

    The projection is intentionally honest about missing observation sources.
    Durable configuration/capability facts can prove unsupported, disabled or
    degraded states, but they do not prove a healthy live media/recorder
    runtime. Later ZLM observation hooks can upgrade those layers without
    changing this API contract.
    """

    @staticmethod
    def _services(
        device: Device | None,
    ) -> set[str]:
        if device is None:
            return set()
        raw = (
            device.capabilities_json
            or {}
        ).get(
            "onvif_services",
            [],
        )
        if not isinstance(raw, list):
            return set()
        return {
            item.strip().casefold()
            for item in raw
            if isinstance(item, str)
            and item.strip()
        }

    @staticmethod
    def _disabled(
        camera: Camera,
    ) -> CapabilityHealthLayer | None:
        if camera.retired_at is not None:
            return CapabilityHealthLayer(
                state="disabled",
                reason="camera_retired",
            )
        if not camera.enabled:
            return CapabilityHealthLayer(
                state="disabled",
                reason="camera_disabled",
            )
        return None

    @staticmethod
    def _control(
        session: Session,
        *,
        camera: Camera,
        device: Device | None,
    ) -> CapabilityHealthLayer:
        if (
            device is None
            or device.adapter_type
            != "onvif"
        ):
            return CapabilityHealthLayer(
                state="unsupported",
                reason="onvif_control_not_supported",
            )
        if camera.retired_at is not None:
            return CapabilityHealthLayer(
                state="disabled",
                reason="camera_retired",
            )
        if not device.enabled:
            return CapabilityHealthLayer(
                state="disabled",
                reason="device_disabled",
            )
        endpoint = session.scalar(
            select(DeviceEndpoint.id)
            .where(
                DeviceEndpoint.device_id
                == device.id,
                DeviceEndpoint.type
                == "onvif",
                DeviceEndpoint.enabled
                .is_(True),
            )
            .limit(1)
        )
        if endpoint is None:
            return CapabilityHealthLayer(
                state="degraded",
                reason="onvif_endpoint_unavailable",
            )
        return CapabilityHealthLayer(
            state="unknown",
            reason="awaiting_control_observation",
        )

    @classmethod
    def _media(
        cls,
        session: Session,
        *,
        camera: Camera,
        zlm_health: Any | None,
    ) -> CapabilityHealthLayer:
        disabled = cls._disabled(camera)
        if disabled is not None:
            return disabled

        profiles = {
            item.id: item
            for item in camera.stream_profiles
        }
        if not camera.stream_bindings:
            return CapabilityHealthLayer(
                state="degraded",
                reason="stream_bindings_missing",
            )

        unavailable: list[str] = []
        invalid: list[str] = []
        for binding in (
            camera.stream_bindings
        ):
            profile = profiles.get(
                binding.stream_profile_id
            )
            if profile is None:
                invalid.append(
                    binding.purpose
                )
                continue
            if (
                profile.status
                == "unavailable"
            ):
                unavailable.append(
                    binding.purpose
                )

        if invalid:
            return CapabilityHealthLayer(
                state="degraded",
                reason="stream_binding_invalid",
                details={
                    "purposes": sorted(
                        invalid
                    ),
                },
            )
        if unavailable:
            return CapabilityHealthLayer(
                state="degraded",
                reason="bound_stream_unavailable",
                details={
                    "purposes": sorted(
                        unavailable
                    ),
                },
            )

        observed: list[
            tuple[str, Any]
        ] = []
        if (
            zlm_health is not None
            and hasattr(
                zlm_health,
                "media",
            )
        ):
            for binding in (
                camera.stream_bindings
            ):
                item = zlm_health.media(
                    binding.stream_profile_id
                )
                if item is not None:
                    observed.append(
                        (
                            binding.purpose,
                            item,
                        )
                    )

        online = sorted(
            purpose
            for purpose, item
            in observed
            if bool(
                getattr(
                    item,
                    "online",
                    False,
                )
            )
        )
        if online:
            return CapabilityHealthLayer(
                state="healthy",
                details={
                    "online_purposes": online,
                },
            )

        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id
                == camera.id
            )
        )
        record_binding = next(
            (
                item
                for item
                in camera.stream_bindings
                if item.purpose == "RECORD"
            ),
            None,
        )
        recording_required = False
        if (
            policy is not None
            and record_binding is not None
        ):
            decision = (
                RecordingArbiterService
                .evaluate(
                    session,
                    camera_id=camera.id,
                    camera_enabled=(
                        camera.enabled
                    ),
                    policy=policy,
                )
            )
            recording_required = (
                decision.mode != "off"
            )

        record_observation = (
            zlm_health.media(
                record_binding.stream_profile_id
            )
            if (
                recording_required
                and record_binding is not None
                and zlm_health is not None
                and hasattr(
                    zlm_health,
                    "media",
                )
            )
            else None
        )
        if (
            record_observation is not None
            and not bool(
                getattr(
                    record_observation,
                    "online",
                    False,
                )
            )
        ):
            return CapabilityHealthLayer(
                state="degraded",
                reason="recording_media_offline",
                details={
                    "observed_at": (
                        record_observation
                        .observed_at
                        .isoformat()
                    ),
                },
            )

        return CapabilityHealthLayer(
            state="unknown",
            reason="awaiting_media_observation",
        )

    @classmethod
    def _recording(
        cls,
        session: Session,
        *,
        camera: Camera,
        zlm_health: Any | None,
    ) -> CapabilityHealthLayer:
        disabled = cls._disabled(camera)
        if disabled is not None:
            return disabled

        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id
                == camera.id
            )
        )
        if (
            policy is None
            or not policy.enabled
            or (
                policy.baseline_mode
                == "disabled"
                and not (
                    policy.event_recording_enabled
                )
            )
        ):
            return CapabilityHealthLayer(
                state="disabled",
                reason="recording_not_enabled",
            )

        binding = next(
            (
                item
                for item
                in camera.stream_bindings
                if item.purpose == "RECORD"
            ),
            None,
        )
        if binding is None:
            return CapabilityHealthLayer(
                state="degraded",
                reason="recording_stream_binding_missing",
            )
        profile = next(
            (
                item
                for item
                in camera.stream_profiles
                if item.id
                == binding.stream_profile_id
            ),
            None,
        )
        if profile is None:
            return CapabilityHealthLayer(
                state="degraded",
                reason="recording_stream_binding_invalid",
            )
        if (
            profile.status
            == "unavailable"
        ):
            return CapabilityHealthLayer(
                state="degraded",
                reason="recording_stream_unavailable",
            )

        decision = (
            RecordingArbiterService
            .evaluate(
                session,
                camera_id=camera.id,
                camera_enabled=(
                    camera.enabled
                ),
                policy=policy,
            )
        )
        if decision.mode == "off":
            return CapabilityHealthLayer(
                state="disabled",
                reason="recording_not_currently_required",
            )

        media_observation = (
            zlm_health.media(
                profile.id
            )
            if (
                zlm_health is not None
                and hasattr(
                    zlm_health,
                    "media",
                )
            )
            else None
        )
        if (
            media_observation is not None
            and not bool(
                getattr(
                    media_observation,
                    "online",
                    False,
                )
            )
        ):
            return CapabilityHealthLayer(
                state="degraded",
                reason="recording_source_offline",
                details={
                    "observed_at": (
                        media_observation
                        .observed_at
                        .isoformat()
                    ),
                },
            )

        recording_observation = (
            zlm_health.recording(
                profile.id
            )
            if (
                zlm_health is not None
                and hasattr(
                    zlm_health,
                    "recording",
                )
            )
            else None
        )
        if recording_observation is not None:
            media_online = (
                media_observation is not None
                and bool(
                    getattr(
                        media_observation,
                        "online",
                        False,
                    )
                )
            )
            media_continuity = (
                getattr(
                    media_observation,
                    "continuity_id",
                    None,
                )
                if media_online
                else None
            )
            recording_continuity = (
                getattr(
                    recording_observation,
                    "continuity_id",
                    None,
                )
            )
            same_generation = (
                not media_online
                or media_continuity is None
                or (
                    recording_continuity
                    is not None
                    and recording_continuity
                    == media_continuity
                )
            )
            if same_generation:
                return CapabilityHealthLayer(
                    state="healthy",
                    details={
                        "last_finalized_at": (
                            recording_observation
                            .finalized_at
                            .isoformat()
                        ),
                        "mode": decision.mode,
                    },
                )

        return CapabilityHealthLayer(
            state="unknown",
            reason="awaiting_recording_observation",
            details={
                "mode": decision.mode,
            },
        )

    @classmethod
    def _events(
        cls,
        *,
        camera: Camera,
        device: Device | None,
        services: set[str],
        event_runtime: Any | None,
    ) -> CapabilityHealthLayer:
        if (
            device is None
            or device.adapter_type
            != "onvif"
            or "events"
            not in services
        ):
            return CapabilityHealthLayer(
                state="unsupported",
                reason="onvif_events_not_supported",
            )
        disabled = cls._disabled(camera)
        if disabled is not None:
            return disabled
        if not device.enabled:
            return CapabilityHealthLayer(
                state="disabled",
                reason="device_disabled",
            )

        runtime = (
            event_runtime.status(
                device.id
            )
            if (
                event_runtime is not None
                and hasattr(
                    event_runtime,
                    "status",
                )
            )
            else None
        )
        if runtime is None:
            return CapabilityHealthLayer(
                state="unknown",
                reason="event_subscription_unobserved",
            )

        state = getattr(
            runtime,
            "state",
            "unknown",
        )
        error_code = getattr(
            runtime,
            "error_code",
            None,
        )
        if state == "healthy":
            return CapabilityHealthLayer(
                state="healthy",
                reason=None,
            )
        if state == "degraded":
            return CapabilityHealthLayer(
                state="degraded",
                reason=(
                    error_code
                    or "event_subscription_degraded"
                ),
            )
        return CapabilityHealthLayer(
            state="unknown",
            reason="event_subscription_starting",
        )

    @classmethod
    def _ptz(
        cls,
        session: Session,
        *,
        camera: Camera,
        device: Device | None,
        services: set[str],
    ) -> CapabilityHealthLayer:
        if (
            device is None
            or device.adapter_type
            != "onvif"
            or "ptz" not in services
        ):
            return CapabilityHealthLayer(
                state="unsupported",
                reason="ptz_not_supported",
            )
        disabled = cls._disabled(camera)
        if disabled is not None:
            return disabled
        if not device.enabled:
            return CapabilityHealthLayer(
                state="disabled",
                reason="device_disabled",
            )
        endpoint = session.scalar(
            select(DeviceEndpoint.id)
            .where(
                DeviceEndpoint.device_id
                == device.id,
                DeviceEndpoint.type
                == "onvif",
                DeviceEndpoint.enabled
                .is_(True),
            )
            .limit(1)
        )
        if endpoint is None:
            return CapabilityHealthLayer(
                state="degraded",
                reason="onvif_endpoint_unavailable",
            )
        return CapabilityHealthLayer(
            state="unknown",
            reason="awaiting_ptz_observation",
        )

    @classmethod
    def _clock(
        cls,
        *,
        camera: Camera,
        device: Device | None,
        clock_store: Any | None,
    ) -> CapabilityHealthLayer:
        if (
            device is None
            or device.adapter_type
            != "onvif"
        ):
            return CapabilityHealthLayer(
                state="unsupported",
                reason="device_clock_not_supported",
            )
        if camera.time_sync_mode == "ignore":
            return CapabilityHealthLayer(
                state="disabled",
                reason="clock_monitoring_ignored",
            )
        disabled = cls._disabled(camera)
        if disabled is not None:
            return disabled

        projection = (
            clock_store.get(
                device.id
            )
            if (
                clock_store is not None
                and hasattr(
                    clock_store,
                    "get",
                )
            )
            else None
        )
        if projection is None:
            return CapabilityHealthLayer(
                state="unknown",
                reason="clock_not_measured",
            )

        health = getattr(
            projection,
            "health",
            "unknown",
        )
        state = {
            "healthy": "healthy",
            "warning": "degraded",
            "critical": "critical",
            "unsupported": "unsupported",
        }.get(
            health,
            "unknown",
        )
        return CapabilityHealthLayer(
            state=state,
            reason=getattr(
                projection,
                "error_code",
                None,
            ),
            details={
                "quality": getattr(
                    projection,
                    "quality",
                    "unknown",
                ),
                "measured_at": (
                    projection.measured_at
                    .isoformat()
                    if getattr(
                        projection,
                        "measured_at",
                        None,
                    )
                    is not None
                    else None
                ),
            },
        )

    @classmethod
    def project(
        cls,
        session: Session,
        *,
        camera: Camera,
        clock_store: Any | None = None,
        event_runtime: Any | None = None,
        zlm_health: Any | None = None,
    ) -> CameraCapabilityHealth:
        device = (
            session.get(
                Device,
                camera.device_id,
            )
            if camera.device_id
            is not None
            else None
        )
        services = cls._services(
            device
        )
        return CameraCapabilityHealth(
            camera_id=camera.id,
            control=cls._control(
                session,
                camera=camera,
                device=device,
            ),
            media=cls._media(
                session,
                camera=camera,
                zlm_health=zlm_health,
            ),
            recording=cls._recording(
                session,
                camera=camera,
                zlm_health=zlm_health,
            ),
            events=cls._events(
                camera=camera,
                device=device,
                services=services,
                event_runtime=(
                    event_runtime
                ),
            ),
            ptz=cls._ptz(
                session,
                camera=camera,
                device=device,
                services=services,
            ),
            clock=cls._clock(
                camera=camera,
                device=device,
                clock_store=clock_store,
            ),
        )
