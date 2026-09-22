from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.integrations.onvif import OnvifInspection, OnvifProfileProbe

from .models import (
    Camera,
    CameraStreamProfile,
    Device,
    DeviceCredential,
    DeviceEndpoint,
)


@dataclass(frozen=True, slots=True)
class OnvifStoredConnection:
    host: str
    port: int
    username: str = field(repr=False)
    password: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class OnvifCapabilityDiff:
    profiles_added: tuple[str, ...] = ()
    profiles_missing: tuple[str, ...] = ()
    profiles_changed: tuple[str, ...] = ()
    profiles_recovered: tuple[str, ...] = ()
    profiles_unmapped_added: tuple[str, ...] = ()
    capabilities_added: tuple[str, ...] = ()
    capabilities_removed: tuple[str, ...] = ()


class OnvifCapabilityRefreshService:
    """Refresh persisted ONVIF capability facts without deleting user config."""

    def __init__(self, settings: Settings) -> None:
        self.secret_store = SecretStore(settings)

    @staticmethod
    def _cameras(
        session: Session,
        *,
        device_id: uuid.UUID,
    ) -> list[Camera]:
        return list(
            session.scalars(
                select(Camera)
                .where(Camera.device_id == device_id)
                .order_by(Camera.channel_key, Camera.id)
            )
        )

    def connection(
        self,
        session: Session,
        camera: Camera,
    ) -> tuple[Device, OnvifStoredConnection]:
        if camera.device_id is None:
            raise ApiError(
                status_code=409,
                code="camera_onvif_unavailable",
                message="Camera is not attached to an ONVIF device.",
            )

        device = session.get(Device, camera.device_id)
        if (
            device is None
            or device.adapter_type != "onvif"
            or not device.enabled
        ):
            raise ApiError(
                status_code=409,
                code="camera_onvif_unavailable",
                message="Camera does not have an enabled ONVIF device.",
            )

        endpoint = session.scalar(
            select(DeviceEndpoint)
            .where(
                DeviceEndpoint.device_id == device.id,
                DeviceEndpoint.type == "onvif",
                DeviceEndpoint.enabled.is_(True),
            )
            .order_by(
                DeviceEndpoint.priority,
                DeviceEndpoint.id,
            )
            .limit(1)
        )
        if endpoint is None:
            raise ApiError(
                status_code=409,
                code="camera_onvif_unavailable",
                message="Camera ONVIF endpoint is unavailable.",
            )

        credential = session.scalar(
            select(DeviceCredential)
            .where(
                DeviceCredential.device_id == device.id,
                DeviceCredential.kind == "onvif",
            )
            .order_by(
                (
                    DeviceCredential.endpoint_id
                    == endpoint.id
                ).desc(),
                DeviceCredential.id,
            )
            .limit(1)
        )
        if credential is None:
            raise ApiError(
                status_code=409,
                code="device_credential_unavailable",
                message="ONVIF device credentials are unavailable.",
            )

        try:
            value = self.secret_store.read_json(
                session,
                credential.secret_ref,
                kind="onvif_credential",
                owner_type="device",
                owner_id=device.id,
            )
        except Exception as exc:
            raise ApiError(
                status_code=409,
                code="device_credential_unavailable",
                message="ONVIF device credentials are unavailable.",
            ) from exc

        username = value.get("username")
        password = value.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise ApiError(
                status_code=409,
                code="device_credential_unavailable",
                message="ONVIF device credentials are unavailable.",
            )

        return device, OnvifStoredConnection(
            host=endpoint.host,
            port=endpoint.port or 80,
            username=username,
            password=password,
        )

    def _stream_uri(
        self,
        session: Session,
        profile: CameraStreamProfile,
    ) -> str | None:
        if profile.stream_uri_ref is None:
            return None
        try:
            value = self.secret_store.read_json(
                session,
                profile.stream_uri_ref,
                kind="rtsp_uri",
                owner_type="camera_stream_profile",
                owner_id=profile.id,
            )
        except Exception:
            return None
        uri = value.get("uri")
        return uri if isinstance(uri, str) and uri else None

    @staticmethod
    def _has_drift(profile: CameraStreamProfile) -> bool:
        metadata = profile.metadata_json or {}
        return isinstance(metadata.get("capability_drift"), dict)

    def verification_profiles(
        self,
        session: Session,
        *,
        device_id: uuid.UUID,
        inspection: OnvifInspection,
    ) -> tuple[OnvifProfileProbe, ...]:
        """Return only profile sources that require media verification.

        Metadata-only refreshes remain cheap. New profiles, recovered profiles,
        and changed/missing URI secrets must pass the existing ZLM source probe
        before their source material is persisted.
        """
        cameras = self._cameras(
            session,
            device_id=device_id,
        )
        by_channel = {
            camera.channel_key: camera
            for camera in cameras
        }
        existing: dict[
            str,
            tuple[Camera, CameraStreamProfile],
        ] = {
            profile.adapter_profile_key: (camera, profile)
            for camera in cameras
            for profile in camera.stream_profiles
        }

        verify: dict[str, OnvifProfileProbe] = {}
        for probe in inspection.profiles:
            channel_key = probe.video_source_token or "default"
            current = existing.get(probe.token)
            usable = bool(
                probe.stream_uri_available
                and probe.stream_uri
            )
            if current is None:
                if usable and channel_key in by_channel:
                    verify[probe.token] = probe
                continue

            camera, profile = current
            if channel_key != camera.channel_key or not usable:
                continue

            current_uri = self._stream_uri(
                session,
                profile,
            )
            if (
                self._has_drift(profile)
                or current_uri != probe.stream_uri
            ):
                verify[probe.token] = probe

        return tuple(
            verify[token]
            for token in sorted(verify)
        )

    @staticmethod
    def _profile_fields(
        profile: CameraStreamProfile,
    ) -> tuple[Any, ...]:
        return (
            profile.video_source_key,
            profile.name,
            profile.codec,
            profile.width,
            profile.height,
            profile.fps,
            profile.bitrate_kbps,
            profile.gop_seconds,
            profile.audio_codec,
            profile.has_audio,
        )

    @staticmethod
    def _probe_fields(
        probe: OnvifProfileProbe,
    ) -> tuple[Any, ...]:
        return (
            probe.video_source_token,
            probe.name,
            probe.codec,
            probe.width,
            probe.height,
            probe.fps,
            probe.bitrate_kbps,
            probe.gop_seconds,
            probe.audio_codec,
            probe.has_audio,
        )

    @staticmethod
    def _drift_metadata(
        profile: CameraStreamProfile,
        *,
        reason: str,
        detected_at: str,
    ) -> dict[str, Any]:
        metadata = dict(profile.metadata_json or {})
        metadata["capability_drift"] = {
            "state": "missing",
            "reason": reason,
            "detected_at": detected_at,
        }
        return metadata

    @staticmethod
    def _clear_drift_metadata(
        profile: CameraStreamProfile,
    ) -> dict[str, Any]:
        metadata = dict(profile.metadata_json or {})
        metadata.pop("capability_drift", None)
        return metadata

    def _replace_stream_uri(
        self,
        session: Session,
        *,
        profile: CameraStreamProfile,
        uri: str,
    ) -> None:
        if profile.stream_uri_ref is None:
            profile.stream_uri_ref = self.secret_store.create_json(
                session,
                kind="rtsp_uri",
                owner_type="camera_stream_profile",
                owner_id=profile.id,
                value={"uri": uri},
            )
            return

        old_stream_ref = profile.stream_uri_ref
        profile.stream_uri_ref = self.secret_store.create_json(
            session,
            kind="rtsp_uri",
            owner_type="camera_stream_profile",
            owner_id=profile.id,
            value={"uri": uri},
        )
        session.flush()
        try:
            self.secret_store.delete(
                session,
                old_stream_ref,
                kind="rtsp_uri",
                owner_type="camera_stream_profile",
                owner_id=profile.id,
            )
        except KeyError:
            # The old reference may already be stale; the staged replacement
            # is authoritative once the profile points at the new record.
            pass

    def apply(
        self,
        session: Session,
        *,
        device_id: uuid.UUID,
        inspection: OnvifInspection,
        verified_tokens: set[str],
    ) -> tuple[
        list[Camera],
        OnvifCapabilityDiff,
        dict[uuid.UUID, set[uuid.UUID]],
    ]:
        device = session.get(Device, device_id)
        if device is None or device.adapter_type != "onvif":
            raise ApiError(
                status_code=409,
                code="camera_onvif_unavailable",
                message="ONVIF device is unavailable.",
            )
        if (
            device.hardware_id
            and inspection.device.hardware_id
            and device.hardware_id
            != inspection.device.hardware_id
        ):
            raise ApiError(
                status_code=409,
                code="onvif_device_identity_changed",
                message=(
                    "The ONVIF endpoint now reports a different hardware "
                    "identity; capability refresh was not applied."
                ),
            )

        cameras = self._cameras(
            session,
            device_id=device.id,
        )
        if not cameras:
            raise ApiError(
                status_code=409,
                code="onvif_device_topology_invalid",
                message="Imported ONVIF device has no Camera channels.",
            )

        camera_by_channel = {
            camera.channel_key: camera
            for camera in cameras
        }
        camera_by_id = {
            camera.id: camera
            for camera in cameras
        }
        existing = {
            profile.adapter_profile_key: profile
            for camera in cameras
            for profile in camera.stream_profiles
        }
        probes = {
            probe.token: probe
            for probe in inspection.profiles
        }
        bound_ids = {
            binding.stream_profile_id
            for camera in cameras
            for binding in camera.stream_bindings
        }
        restart_profiles_by_camera: dict[
            uuid.UUID,
            set[uuid.UUID],
        ] = {}

        previous_services = {
            item
            for item in (
                device.capabilities_json or {}
            ).get("onvif_services", [])
            if isinstance(item, str)
        }
        current_services = set(
            inspection.capabilities
        )
        now = utc_now()
        now_text = now.isoformat()

        device.manufacturer = inspection.device.manufacturer
        device.model = inspection.device.model
        device.serial_number = inspection.device.serial_number
        if inspection.device.hardware_id:
            device.hardware_id = inspection.device.hardware_id
        device.capabilities_json = {
            "onvif_services": sorted(current_services),
        }
        device.capabilities_updated_at = now

        missing: list[str] = []
        changed: list[str] = []
        recovered: list[str] = []

        for token, profile in sorted(
            existing.items(),
            key=lambda item: item[0],
        ):
            probe = probes.get(token)
            camera = camera_by_id[profile.camera_id]
            if probe is None:
                reason = "profile_missing"
            elif (
                probe.video_source_token or "default"
            ) != camera.channel_key:
                reason = "channel_changed"
            elif (
                not probe.stream_uri_available
                or not probe.stream_uri
            ):
                reason = "stream_uri_unavailable"
            else:
                reason = ""

            if reason:
                missing.append(token)
                profile.status = "unavailable"
                profile.metadata_json = self._drift_metadata(
                    profile,
                    reason=reason,
                    detected_at=now_text,
                )
                continue

            assert probe is not None
            assert probe.stream_uri is not None
            had_drift = self._has_drift(profile)
            metadata_changed = (
                self._profile_fields(profile)
                != self._probe_fields(probe)
            )
            current_uri = self._stream_uri(
                session,
                profile,
            )
            uri_changed = current_uri != probe.stream_uri

            if (
                (had_drift or uri_changed)
                and token not in verified_tokens
            ):
                raise ApiError(
                    status_code=409,
                    code="onvif_profile_verification_required",
                    message=(
                        "A changed ONVIF profile source was not verified "
                        "before capability refresh."
                    ),
                    details={"profile_token": token},
                )

            profile.video_source_key = (
                probe.video_source_token
            )
            profile.name = probe.name
            profile.codec = probe.codec
            profile.width = probe.width
            profile.height = probe.height
            profile.fps = probe.fps
            profile.bitrate_kbps = (
                probe.bitrate_kbps
            )
            profile.gop_seconds = (
                probe.gop_seconds
            )
            profile.audio_codec = (
                probe.audio_codec
            )
            profile.has_audio = probe.has_audio
            profile.metadata_json = (
                self._clear_drift_metadata(
                    profile
                )
            )

            if uri_changed:
                self._replace_stream_uri(
                    session,
                    profile=profile,
                    uri=probe.stream_uri,
                )
                if profile.id in bound_ids:
                    restart_profiles_by_camera.setdefault(
                        profile.camera_id,
                        set(),
                    ).add(profile.id)

            if token in verified_tokens:
                profile.status = "available"
                profile.last_verified_at = now
            if metadata_changed or uri_changed:
                changed.append(token)
            if had_drift:
                recovered.append(token)

        added: list[str] = []
        unmapped_added: list[str] = []
        for token, probe in sorted(
            probes.items(),
            key=lambda item: item[0],
        ):
            if token in existing:
                continue
            added.append(token)
            channel_key = (
                probe.video_source_token
                or "default"
            )
            camera = camera_by_channel.get(
                channel_key
            )
            if (
                camera is None
                or not probe.stream_uri_available
                or not probe.stream_uri
            ):
                unmapped_added.append(token)
                continue
            if token not in verified_tokens:
                raise ApiError(
                    status_code=409,
                    code="onvif_profile_verification_required",
                    message=(
                        "A new ONVIF profile source was not verified "
                        "before capability refresh."
                    ),
                    details={"profile_token": token},
                )

            profile = CameraStreamProfile(
                camera_id=camera.id,
                adapter_profile_key=probe.token,
                video_source_key=probe.video_source_token,
                name=probe.name,
                codec=probe.codec,
                width=probe.width,
                height=probe.height,
                fps=probe.fps,
                bitrate_kbps=probe.bitrate_kbps,
                gop_seconds=probe.gop_seconds,
                audio_codec=probe.audio_codec,
                has_audio=probe.has_audio,
                status="available",
                discovered_at=now,
                last_verified_at=now,
                metadata_json={},
            )
            camera.stream_profiles.append(
                profile
            )
            session.flush()
            profile.stream_uri_ref = (
                self.secret_store.create_json(
                    session,
                    kind="rtsp_uri",
                    owner_type="camera_stream_profile",
                    owner_id=profile.id,
                    value={"uri": probe.stream_uri},
                )
            )

        for camera_id in restart_profiles_by_camera:
            camera_by_id[camera_id].config_revision += 1

        session.flush()
        return (
            cameras,
            OnvifCapabilityDiff(
                profiles_added=tuple(added),
                profiles_missing=tuple(missing),
                profiles_changed=tuple(changed),
                profiles_recovered=tuple(recovered),
                profiles_unmapped_added=tuple(
                    unmapped_added
                ),
                capabilities_added=tuple(
                    sorted(
                        current_services
                        - previous_services
                    )
                ),
                capabilities_removed=tuple(
                    sorted(
                        previous_services
                        - current_services
                    )
                ),
            ),
            restart_profiles_by_camera,
        )
