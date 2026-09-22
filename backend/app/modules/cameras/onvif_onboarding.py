from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.integrations.onvif import OnvifInspection, OnvifProfileProbe

from .models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    DeviceCredential,
    DeviceEndpoint,
    DiscoveryCandidate,
)


class OnvifOnboardingService:
    def __init__(self, settings: Settings) -> None:
        self.secret_store = SecretStore(settings)

    @staticmethod
    def _profile_score(profile: OnvifProfileProbe) -> tuple[int, float, int]:
        pixels = (profile.width or 0) * (profile.height or 0)
        return (
            pixels,
            profile.fps or 0.0,
            profile.bitrate_kbps or 0,
        )

    @staticmethod
    def _usable_profiles(
        inspection: OnvifInspection,
        selected_tokens: list[str] | None,
    ) -> list[OnvifProfileProbe]:
        by_token = {profile.token: profile for profile in inspection.profiles}

        if selected_tokens is None:
            selected = list(inspection.profiles)
        else:
            requested = set(selected_tokens)
            missing = requested - set(by_token)
            if missing:
                raise ApiError(
                    status_code=400,
                    code="invalid_onvif_profile_tokens",
                    message="One or more ONVIF profiles do not exist.",
                    details={"profile_tokens": sorted(missing)},
                )
            selected = [
                profile
                for profile in inspection.profiles
                if profile.token in requested
            ]

        usable = [
            profile
            for profile in selected
            if profile.stream_uri_available and profile.stream_uri
        ]
        if not usable:
            raise ApiError(
                status_code=422,
                code="onvif_no_usable_profiles",
                message="The ONVIF device exposes no usable RTSP profiles.",
            )
        return usable

    @staticmethod
    def _existing_device(
        session: Session,
        *,
        inspection: OnvifInspection,
    ) -> Device | None:
        info = inspection.device
        if info.hardware_id:
            return session.scalar(
                select(Device).where(
                    Device.adapter_type == "onvif",
                    Device.hardware_id == info.hardware_id,
                )
            )

        if info.serial_number and info.manufacturer and info.model:
            matches = list(
                session.scalars(
                    select(Device).where(
                        Device.adapter_type == "onvif",
                        Device.serial_number == info.serial_number,
                        Device.manufacturer == info.manufacturer,
                        Device.model == info.model,
                    )
                )
            )
            if len(matches) > 1:
                raise ApiError(
                    status_code=409,
                    code="onvif_device_identity_ambiguous",
                    message=(
                        "More than one imported ONVIF device matches "
                        "this stable identity."
                    ),
                )
            return matches[0] if matches else None

        return None

    @staticmethod
    def _ensure_endpoint_available(
        session: Session,
        *,
        host: str,
        port: int,
        existing_device_id: uuid.UUID | None,
    ) -> None:
        endpoint = session.scalar(
            select(DeviceEndpoint)
            .join(Device, Device.id == DeviceEndpoint.device_id)
            .where(
                Device.adapter_type == "onvif",
                DeviceEndpoint.type == "onvif",
                DeviceEndpoint.host == host,
                DeviceEndpoint.port == port,
            )
        )
        if (
            endpoint is not None
            and endpoint.device_id != existing_device_id
        ):
            raise ApiError(
                status_code=409,
                code="onvif_device_already_exists",
                message=(
                    "This ONVIF endpoint belongs to another imported device."
                ),
            )

    def _reconfigure_existing(
        self,
        session: Session,
        *,
        device: Device,
        inspection: OnvifInspection,
        host: str,
        port: int,
        username: str,
        password: str,
        discovery_candidate_id: uuid.UUID | None,
    ) -> tuple[Device, list[Camera], bool]:
        usable = {
            item.token: item
            for item in inspection.profiles
            if item.stream_uri_available and item.stream_uri
        }
        cameras = list(
            session.scalars(
                select(Camera)
                .where(Camera.device_id == device.id)
                .order_by(Camera.channel_key, Camera.id)
            )
        )
        if not cameras:
            raise ApiError(
                status_code=409,
                code="onvif_device_topology_invalid",
                message="Imported ONVIF device has no Camera channels.",
            )

        profile_updates: list[
            tuple[CameraStreamProfile, OnvifProfileProbe]
        ] = []
        for camera in cameras:
            for model in camera.stream_profiles:
                probe = usable.get(model.adapter_profile_key)
                if (
                    probe is None
                    or (probe.video_source_token or "default")
                    != camera.channel_key
                ):
                    raise ApiError(
                        status_code=409,
                        code="onvif_device_topology_changed",
                        message=(
                            "ONVIF channel/profile identity changed; "
                            "automatic address refresh was not applied."
                        ),
                        details={
                            "camera_id": str(camera.id),
                            "profile_token": model.adapter_profile_key,
                        },
                    )
                profile_updates.append((model, probe))

        self._ensure_endpoint_available(
            session,
            host=host,
            port=port,
            existing_device_id=device.id,
        )

        now = utc_now()
        device.manufacturer = inspection.device.manufacturer
        device.model = inspection.device.model
        device.serial_number = inspection.device.serial_number
        device.hardware_id = (
            inspection.device.hardware_id or device.hardware_id
        )
        device.capabilities_json = {
            "onvif_services": list(inspection.capabilities),
        }
        device.capabilities_updated_at = now

        endpoint = next(
            (
                item
                for item in sorted(
                    device.endpoints,
                    key=lambda value: (value.priority, str(value.id)),
                )
                if item.type == "onvif"
            ),
            None,
        )
        if endpoint is None:
            endpoint = DeviceEndpoint(
                device_id=device.id,
                type="onvif",
                host=host,
                port=port,
                scheme="http",
                path=None,
                priority=100,
                enabled=True,
                last_verified_at=now,
                metadata_json={},
            )
            session.add(endpoint)
            session.flush()
        else:
            endpoint.host = host
            endpoint.port = port
            endpoint.scheme = "http"
            endpoint.path = None
            endpoint.enabled = True
            endpoint.last_verified_at = now

        credential = next(
            (
                item
                for item in device.credentials
                if item.kind == "onvif"
            ),
            None,
        )
        if credential is None:
            secret_ref = self.secret_store.create_json(
                session,
                kind="onvif_credential",
                owner_type="device",
                owner_id=device.id,
                value={
                    "username": username,
                    "password": password,
                },
            )
            credential = DeviceCredential(
                device_id=device.id,
                endpoint_id=endpoint.id,
                kind="onvif",
                secret_ref=secret_ref,
            )
            session.add(credential)
        else:
            credential.endpoint_id = endpoint.id
            old_credential_ref = credential.secret_ref
            try:
                self.secret_store.metadata(
                    session,
                    old_credential_ref,
                    kind="onvif_credential",
                    owner_type="device",
                    owner_id=device.id,
                )
            except KeyError as exc:
                raise ApiError(
                    status_code=409,
                    code="device_credential_unavailable",
                    message="ONVIF device credential secret is unavailable.",
                ) from exc

            candidate_credential_ref = (
                self.secret_store.create_json(
                    session,
                    kind="onvif_credential",
                    owner_type="device",
                    owner_id=device.id,
                    value={
                        "username": username,
                        "password": password,
                    },
                )
            )
            credential.secret_ref = (
                candidate_credential_ref
            )
            session.flush()
            self.secret_store.delete(
                session,
                old_credential_ref,
                kind="onvif_credential",
                owner_type="device",
                owner_id=device.id,
            )

        for model, probe in profile_updates:
            model.video_source_key = probe.video_source_token
            model.name = probe.name
            model.codec = probe.codec
            model.width = probe.width
            model.height = probe.height
            model.fps = probe.fps
            model.bitrate_kbps = probe.bitrate_kbps
            model.gop_seconds = probe.gop_seconds
            model.audio_codec = probe.audio_codec
            model.has_audio = probe.has_audio
            model.status = "available"
            model.last_verified_at = now

            assert probe.stream_uri is not None
            if model.stream_uri_ref is None:
                model.stream_uri_ref = (
                    self.secret_store.create_json(
                        session,
                        kind="rtsp_uri",
                        owner_type="camera_stream_profile",
                        owner_id=model.id,
                        value={"uri": probe.stream_uri},
                    )
                )
            else:
                old_stream_ref = model.stream_uri_ref
                candidate_stream_ref = (
                    self.secret_store.create_json(
                        session,
                        kind="rtsp_uri",
                        owner_type="camera_stream_profile",
                        owner_id=model.id,
                        value={"uri": probe.stream_uri},
                    )
                )
                model.stream_uri_ref = (
                    candidate_stream_ref
                )
                session.flush()
                try:
                    self.secret_store.delete(
                        session,
                        old_stream_ref,
                        kind="rtsp_uri",
                        owner_type="camera_stream_profile",
                        owner_id=model.id,
                    )
                except KeyError:
                    pass

        self._mark_discovery_candidate_imported(
            session,
            candidate_id=discovery_candidate_id,
            host=host,
            port=port,
        )
        session.flush()
        return device, cameras, True

    @staticmethod
    def _mark_discovery_candidate_imported(
        session: Session,
        *,
        candidate_id: uuid.UUID | None,
        host: str,
        port: int,
    ) -> None:
        if candidate_id is None:
            return

        candidate = session.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            raise ApiError(
                status_code=400,
                code="discovery_candidate_not_found",
                message="Discovery candidate was not found.",
            )

        metadata = candidate.metadata_json or {}
        candidate_port = metadata.get("port")
        if (
            candidate.host != host
            or not isinstance(candidate_port, int)
            or candidate_port != port
        ):
            raise ApiError(
                status_code=400,
                code="discovery_candidate_mismatch",
                message="Discovery candidate does not match the ONVIF endpoint.",
            )

        candidate.state = "imported"

    def import_device(
        self,
        session: Session,
        *,
        inspection: OnvifInspection,
        host: str,
        port: int,
        username: str,
        password: str,
        base_name: str | None,
        location: str | None,
        storage_label: str | None,
        selected_profile_tokens: list[str] | None,
        discovery_candidate_id: uuid.UUID | None,
    ) -> tuple[Device, list[Camera], bool]:
        existing = self._existing_device(
            session,
            inspection=inspection,
        )
        if existing is not None:
            return self._reconfigure_existing(
                session,
                device=existing,
                inspection=inspection,
                host=host,
                port=port,
                username=username,
                password=password,
                discovery_candidate_id=discovery_candidate_id,
            )

        self._ensure_endpoint_available(
            session,
            host=host,
            port=port,
            existing_device_id=None,
        )
        profiles = self._usable_profiles(
            inspection,
            selected_profile_tokens,
        )

        device_info = inspection.device
        device_name = (
            base_name
            or device_info.model
            or device_info.manufacturer
            or host
        )

        device = Device(
            name=device_name,
            manufacturer=device_info.manufacturer,
            model=device_info.model,
            serial_number=device_info.serial_number,
            hardware_id=device_info.hardware_id,
            adapter_type="onvif",
            enabled=True,
            capabilities_json={
                "onvif_services": list(inspection.capabilities),
            },
            capabilities_updated_at=utc_now(),
        )
        session.add(device)
        session.flush()

        endpoint = DeviceEndpoint(
            device_id=device.id,
            type="onvif",
            host=host,
            port=port,
            scheme="http",
            path=None,
            priority=100,
            enabled=True,
            last_verified_at=utc_now(),
            metadata_json={},
        )
        session.add(endpoint)
        session.flush()

        credential_secret_ref = (
            self.secret_store.create_json(
                session,
                kind="onvif_credential",
                owner_type="device",
                owner_id=device.id,
                value={
                    "username": username,
                    "password": password,
                },
            )
        )

        session.add(
            DeviceCredential(
                device_id=device.id,
                endpoint_id=endpoint.id,
                kind="onvif",
                secret_ref=credential_secret_ref,
            )
        )

        grouped: dict[str, list[OnvifProfileProbe]] = defaultdict(list)
        for profile in profiles:
            grouped[profile.video_source_token or "default"].append(profile)

        cameras: list[Camera] = []
        multi_channel = len(grouped) > 1

        for index, (source_key, source_profiles) in enumerate(
            sorted(grouped.items(), key=lambda item: item[0])
        ):
            camera_name = (
                f"{device_name} {index + 1}"
                if multi_channel
                else device_name
            )
            camera = Camera(
                device_id=device.id,
                channel_key=source_key,
                name=camera_name,
                enabled=True,
                location=location,
                storage_label=storage_label,
            )
            session.add(camera)
            session.flush()

            profile_models: list[
                tuple[OnvifProfileProbe, CameraStreamProfile]
            ] = []

            for profile in sorted(
                source_profiles,
                key=lambda item: item.token,
            ):
                model = CameraStreamProfile(
                    camera_id=camera.id,
                    adapter_profile_key=profile.token,
                    video_source_key=profile.video_source_token,
                    name=profile.name,
                    codec=profile.codec,
                    width=profile.width,
                    height=profile.height,
                    fps=profile.fps,
                    bitrate_kbps=profile.bitrate_kbps,
                    gop_seconds=profile.gop_seconds,
                    audio_codec=profile.audio_codec,
                    has_audio=profile.has_audio,
                    status="available",
                    discovered_at=utc_now(),
                    last_verified_at=utc_now(),
                    metadata_json={},
                )
                session.add(model)
                session.flush()

                model.stream_uri_ref = (
                    self.secret_store.create_json(
                        session,
                        kind="rtsp_uri",
                        owner_type="camera_stream_profile",
                        owner_id=model.id,
                        value={"uri": profile.stream_uri},
                    )
                )

                profile_models.append((profile, model))

            high_profile, high_model = max(
                profile_models,
                key=lambda item: self._profile_score(item[0]),
            )
            low_profile, low_model = min(
                profile_models,
                key=lambda item: self._profile_score(item[0]),
            )

            defaults: dict[str, CameraStreamProfile] = {
                "RECORD": high_model,
                "LIVE_HIGH": high_model,
                "LIVE_LOW": low_model,
                "AI_DETECT": low_model,
                "SNAPSHOT": high_model,
            }
            if high_profile.has_audio:
                defaults["AUDIO"] = high_model

            camera.stream_bindings.extend(
                [
                    CameraStreamBinding(
                        camera_id=camera.id,
                        purpose=purpose,
                        stream_profile_id=profile_model.id,
                        selection_mode="auto",
                    )
                    for purpose, profile_model in defaults.items()
                ]
            )
            cameras.append(camera)

        self._mark_discovery_candidate_imported(
            session,
            candidate_id=discovery_candidate_id,
            host=host,
            port=port,
        )
        session.flush()
        return device, cameras, False
