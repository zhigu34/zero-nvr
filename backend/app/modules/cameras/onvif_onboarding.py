from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.integrations.onvif import OnvifInspection, OnvifProfileProbe

from .onvif_capability_snapshot import (
    build_onvif_capability_snapshot,
)
from .models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    DeviceCredential,
    DeviceEndpoint,
    DiscoveryCandidate,
)


@dataclass(frozen=True, slots=True)
class OnvifIdentityAssessment:
    state: str
    matched_device_id: uuid.UUID | None = None
    matched_device_name: str | None = None
    conflicting_device_ids: tuple[uuid.UUID, ...] = ()
    reason: str | None = None


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

    @classmethod
    def verification_profiles(
        cls,
        session: Session,
        *,
        inspection: OnvifInspection,
        selected_tokens: list[str] | None,
        existing_device_id: uuid.UUID | None = None,
    ) -> list[OnvifProfileProbe]:
        """Return the ONVIF profiles that must pass media verification.

        New imports verify the user-selected profile set. Reconfiguration keeps
        the existing Camera/profile topology, so every persisted profile must
        be present and media-verifiable before any credential/URI replacement.
        """
        existing = (
            session.get(
                Device,
                existing_device_id,
            )
            if existing_device_id is not None
            else cls._existing_device(
                session,
                inspection=inspection,
            )
        )
        if (
            existing_device_id is not None
            and (
                existing is None
                or existing.adapter_type != "onvif"
            )
        ):
            raise ApiError(
                status_code=409,
                code="onvif_device_identity_confirmation_invalid",
                message="Confirmed ONVIF device is unavailable.",
            )
        if existing is None:
            return cls._usable_profiles(
                inspection,
                selected_tokens,
            )

        required_tokens = set(
            session.scalars(
                select(
                    CameraStreamProfile.adapter_profile_key
                )
                .join(
                    Camera,
                    Camera.id
                    == CameraStreamProfile.camera_id,
                )
                .where(
                    Camera.device_id
                    == existing.id
                )
            )
        )
        if not required_tokens:
            raise ApiError(
                status_code=409,
                code="onvif_device_topology_invalid",
                message="Imported ONVIF device has no stream profiles.",
            )

        by_token = {
            profile.token: profile
            for profile in inspection.profiles
        }
        verified: list[OnvifProfileProbe] = []
        for token in sorted(
            required_tokens
        ):
            profile = by_token.get(
                token
            )
            if (
                profile is None
                or not profile.stream_uri_available
                or not profile.stream_uri
            ):
                raise ApiError(
                    status_code=409,
                    code="onvif_device_topology_changed",
                    message=(
                        "An imported ONVIF profile is no longer "
                        "available for media verification."
                    ),
                    details={
                        "profile_token": token,
                    },
                )
            verified.append(
                profile
            )
        return verified

    @staticmethod
    def verification_stream_uri(
        profile: OnvifProfileProbe,
        *,
        username: str,
        password: str,
    ) -> str:
        raw = profile.stream_uri
        if not raw:
            raise ApiError(
                status_code=422,
                code="onvif_stream_uri_unavailable",
                message="ONVIF profile has no usable RTSP URI.",
            )

        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError as exc:
            raise ApiError(
                status_code=422,
                code="onvif_stream_uri_invalid",
                message="ONVIF profile returned an invalid RTSP URI.",
            ) from exc

        if (
            parsed.scheme.lower() != "rtsp"
            or not parsed.hostname
        ):
            raise ApiError(
                status_code=422,
                code="onvif_stream_uri_invalid",
                message="ONVIF profile returned an invalid RTSP URI.",
            )

        # Some devices embed authentication in GetStreamUri. Preserve it.
        if parsed.username is not None or (
            not username and not password
        ):
            return raw

        host = parsed.hostname
        display_host = (
            f"[{host}]"
            if ":" in host
            and not host.startswith("[")
            else host
        )
        host_port = (
            f"{display_host}:{port}"
            if port is not None
            else display_host
        )
        auth = (
            f"{quote(username, safe='')}:"
            f"{quote(password, safe='')}@"
        )
        return urlunsplit(
            (
                parsed.scheme,
                f"{auth}{host_port}",
                parsed.path,
                parsed.query,
                parsed.fragment,
            )
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
    def _stable_identity_matches(
        session: Session,
        *,
        inspection: OnvifInspection,
    ) -> list[Device]:
        info = inspection.device
        if info.hardware_id:
            return list(
                session.scalars(
                    select(Device)
                    .where(
                        Device.adapter_type == "onvif",
                        Device.hardware_id == info.hardware_id,
                    )
                    .order_by(Device.id)
                )
            )

        if (
            info.serial_number
            and info.manufacturer
            and info.model
        ):
            return list(
                session.scalars(
                    select(Device)
                    .where(
                        Device.adapter_type == "onvif",
                        Device.serial_number == info.serial_number,
                        Device.manufacturer == info.manufacturer,
                        Device.model == info.model,
                    )
                    .order_by(Device.id)
                )
            )
        return []

    @classmethod
    def _existing_device(
        cls,
        session: Session,
        *,
        inspection: OnvifInspection,
    ) -> Device | None:
        matches = cls._stable_identity_matches(
            session,
            inspection=inspection,
        )
        if len(matches) > 1:
            raise ApiError(
                status_code=409,
                code="onvif_device_identity_ambiguous",
                message=(
                    "More than one imported ONVIF device matches "
                    "this stable identity."
                ),
                details={
                    "device_ids": [
                        str(item.id)
                        for item in matches
                    ],
                },
            )
        return matches[0] if matches else None

    @staticmethod
    def _endpoint_devices(
        session: Session,
        *,
        host: str,
        port: int,
    ) -> list[Device]:
        return list(
            session.scalars(
                select(Device)
                .join(
                    DeviceEndpoint,
                    DeviceEndpoint.device_id
                    == Device.id,
                )
                .where(
                    Device.adapter_type == "onvif",
                    DeviceEndpoint.type == "onvif",
                    DeviceEndpoint.host == host,
                    DeviceEndpoint.port == port,
                )
                .distinct()
                .order_by(Device.id)
            )
        )

    @classmethod
    def identity_assessment(
        cls,
        session: Session,
        *,
        inspection: OnvifInspection,
        host: str,
        port: int,
    ) -> OnvifIdentityAssessment:
        stable_matches = (
            cls._stable_identity_matches(
                session,
                inspection=inspection,
            )
        )
        endpoint_matches = (
            cls._endpoint_devices(
                session,
                host=host,
                port=port,
            )
        )

        if len(stable_matches) > 1:
            return OnvifIdentityAssessment(
                state="identity_conflict",
                conflicting_device_ids=tuple(
                    item.id
                    for item in stable_matches
                ),
                reason="duplicate_stable_identity",
            )
        if len(endpoint_matches) > 1:
            return OnvifIdentityAssessment(
                state="identity_conflict",
                conflicting_device_ids=tuple(
                    item.id
                    for item in endpoint_matches
                ),
                reason="duplicate_endpoint_identity",
            )

        stable = (
            stable_matches[0]
            if stable_matches
            else None
        )
        endpoint = (
            endpoint_matches[0]
            if endpoint_matches
            else None
        )
        if (
            stable is not None
            and endpoint is not None
            and stable.id != endpoint.id
        ):
            return OnvifIdentityAssessment(
                state="identity_conflict",
                matched_device_id=stable.id,
                matched_device_name=stable.name,
                conflicting_device_ids=(
                    stable.id,
                    endpoint.id,
                ),
                reason=(
                    "stable_identity_endpoint_conflict"
                ),
            )
        if stable is not None:
            return OnvifIdentityAssessment(
                state="same_device",
                matched_device_id=stable.id,
                matched_device_name=stable.name,
                reason="stable_identity_match",
            )
        if endpoint is not None:
            return OnvifIdentityAssessment(
                state=(
                    "probable_match_requires_confirmation"
                ),
                matched_device_id=endpoint.id,
                matched_device_name=endpoint.name,
                reason="endpoint_only_match",
            )
        return OnvifIdentityAssessment(
            state="new_device",
            reason="no_existing_identity_match",
        )

    @classmethod
    def resolve_identity(
        cls,
        session: Session,
        *,
        inspection: OnvifInspection,
        host: str,
        port: int,
        confirmed_existing_device_id: (
            uuid.UUID | None
        ) = None,
    ) -> tuple[
        OnvifIdentityAssessment,
        Device | None,
    ]:
        assessment = cls.identity_assessment(
            session,
            inspection=inspection,
            host=host,
            port=port,
        )

        if assessment.state == "identity_conflict":
            raise ApiError(
                status_code=409,
                code="onvif_device_identity_conflict",
                message=(
                    "The ONVIF identity conflicts with existing "
                    "device records. Resolve the conflict before "
                    "importing."
                ),
                details={
                    "reason": assessment.reason,
                    "device_ids": [
                        str(item)
                        for item in (
                            assessment
                            .conflicting_device_ids
                        )
                    ],
                },
            )

        if assessment.state == "same_device":
            if (
                confirmed_existing_device_id
                is not None
                and confirmed_existing_device_id
                != assessment.matched_device_id
            ):
                raise ApiError(
                    status_code=409,
                    code=(
                        "onvif_device_identity_confirmation_invalid"
                    ),
                    message=(
                        "The confirmed existing device does not "
                        "match the stable ONVIF identity."
                    ),
                )
            assert assessment.matched_device_id is not None
            return (
                assessment,
                session.get(
                    Device,
                    assessment.matched_device_id,
                ),
            )

        if (
            assessment.state
            == "probable_match_requires_confirmation"
        ):
            if (
                confirmed_existing_device_id
                != assessment.matched_device_id
            ):
                raise ApiError(
                    status_code=409,
                    code=(
                        "onvif_device_identity_confirmation_required"
                    ),
                    message=(
                        "This endpoint already belongs to an "
                        "existing device, but the ONVIF identity "
                        "is not strong enough to merge "
                        "automatically."
                    ),
                    details={
                        "matched_device_id": str(
                            assessment.matched_device_id
                        ),
                        "matched_device_name": (
                            assessment.matched_device_name
                        ),
                        "reason": assessment.reason,
                    },
                )
            assert assessment.matched_device_id is not None
            return (
                assessment,
                session.get(
                    Device,
                    assessment.matched_device_id,
                ),
            )

        if confirmed_existing_device_id is not None:
            raise ApiError(
                status_code=409,
                code=(
                    "onvif_device_identity_confirmation_invalid"
                ),
                message=(
                    "There is no existing device match to "
                    "confirm."
                ),
            )
        return assessment, None

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
    ) -> tuple[
        Device,
        list[Camera],
        bool,
        dict[uuid.UUID, set[uuid.UUID]],
    ]:
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

        bound_profile_ids = {
            binding.stream_profile_id
            for camera in cameras
            for binding in camera.stream_bindings
        }
        restart_profiles_by_camera: dict[
            uuid.UUID,
            set[uuid.UUID],
        ] = defaultdict(set)

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
        device.capabilities_json = (
            build_onvif_capability_snapshot(
                inspection
            )
        )
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
        credential_changed = False
        candidate_credential = {
            "username": username,
            "password": password,
        }
        if credential is None:
            secret_ref = self.secret_store.create_json(
                session,
                kind="onvif_credential",
                owner_type="device",
                owner_id=device.id,
                value=candidate_credential,
            )
            credential = DeviceCredential(
                device_id=device.id,
                endpoint_id=endpoint.id,
                kind="onvif",
                secret_ref=secret_ref,
            )
            session.add(credential)
            credential_changed = True
        else:
            credential.endpoint_id = endpoint.id
            try:
                current_credential = (
                    self.secret_store.read_json(
                        session,
                        credential.secret_ref,
                        kind="onvif_credential",
                        owner_type="device",
                        owner_id=device.id,
                    )
                )
            except KeyError as exc:
                raise ApiError(
                    status_code=409,
                    code="device_credential_unavailable",
                    message=(
                        "ONVIF device credential secret "
                        "is unavailable."
                    ),
                ) from exc

            credential_changed = (
                current_credential
                != candidate_credential
            )
            if credential_changed:
                old_secret_ref = (
                    credential.secret_ref
                )
                credential.secret_ref = (
                    self.secret_store.create_json(
                        session,
                        kind="onvif_credential",
                        owner_type="device",
                        owner_id=device.id,
                        value=candidate_credential,
                    )
                )
                session.flush()
                self.secret_store.delete(
                    session,
                    old_secret_ref,
                    kind="onvif_credential",
                    owner_type="device",
                    owner_id=device.id,
                )

        for model, probe in profile_updates:
            current_uri: str | None = None
            stream_secret_missing = (
                model.stream_uri_ref is None
            )
            if model.stream_uri_ref is not None:
                try:
                    current_secret = (
                        self.secret_store.read_json(
                            session,
                            model.stream_uri_ref,
                            kind="rtsp_uri",
                            owner_type=(
                                "camera_stream_profile"
                            ),
                            owner_id=model.id,
                        )
                    )
                    raw_current_uri = (
                        current_secret.get("uri")
                    )
                    if isinstance(
                        raw_current_uri,
                        str,
                    ):
                        current_uri = (
                            raw_current_uri
                        )
                except KeyError:
                    current_uri = None
                    stream_secret_missing = True

            assert probe.stream_uri is not None
            stream_uri_changed = (
                current_uri
                != probe.stream_uri
            )

            model.video_source_key = (
                probe.video_source_token
            )
            model.name = probe.name
            model.codec = probe.codec
            model.width = probe.width
            model.height = probe.height
            model.fps = probe.fps
            model.bitrate_kbps = (
                probe.bitrate_kbps
            )
            model.gop_seconds = (
                probe.gop_seconds
            )
            model.audio_codec = (
                probe.audio_codec
            )
            model.has_audio = (
                probe.has_audio
            )
            model.status = "available"
            model.last_verified_at = now

            if stream_secret_missing:
                model.stream_uri_ref = (
                    self.secret_store.create_json(
                        session,
                        kind="rtsp_uri",
                        owner_type=(
                            "camera_stream_profile"
                        ),
                        owner_id=model.id,
                        value={
                            "uri": probe.stream_uri
                        },
                    )
                )
            elif stream_uri_changed:
                old_stream_ref = (
                    model.stream_uri_ref
                )
                model.stream_uri_ref = (
                    self.secret_store.create_json(
                        session,
                        kind="rtsp_uri",
                        owner_type=(
                            "camera_stream_profile"
                        ),
                        owner_id=model.id,
                        value={
                            "uri": probe.stream_uri
                        },
                    )
                )
                session.flush()
                assert old_stream_ref is not None
                self.secret_store.delete(
                    session,
                    old_stream_ref,
                    kind="rtsp_uri",
                    owner_type=(
                        "camera_stream_profile"
                    ),
                    owner_id=model.id,
                )

            if (
                model.id
                in bound_profile_ids
                and stream_uri_changed
            ):
                restart_profiles_by_camera[
                    model.camera_id
                ].add(
                    model.id
                )

        if credential_changed:
            for camera in cameras:
                for binding in (
                    camera.stream_bindings
                ):
                    profile = next(
                        (
                            item
                            for item in (
                                camera.stream_profiles
                            )
                            if item.id
                            == binding.stream_profile_id
                        ),
                        None,
                    )
                    if (
                        profile is None
                        or profile.stream_uri_ref
                        is None
                    ):
                        continue
                    try:
                        value = (
                            self.secret_store
                            .read_json(
                                session,
                                profile.stream_uri_ref,
                                kind="rtsp_uri",
                                owner_type=(
                                    "camera_stream_profile"
                                ),
                                owner_id=profile.id,
                            )
                        )
                        uri = value.get(
                            "uri"
                        )
                        if not isinstance(
                            uri,
                            str,
                        ):
                            continue
                        parsed = urlsplit(
                            uri
                        )
                    except (
                        KeyError,
                        ValueError,
                    ):
                        continue
                    if parsed.username is None:
                        restart_profiles_by_camera[
                            camera.id
                        ].add(
                            profile.id
                        )

        for camera in cameras:
            if (
                restart_profiles_by_camera.get(
                    camera.id
                )
            ):
                camera.config_revision += 1

        self._mark_discovery_candidate_imported(
            session,
            candidate_id=discovery_candidate_id,
            host=host,
            port=port,
        )
        session.flush()
        return (
            device,
            cameras,
            True,
            restart_profiles_by_camera,
        )

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
        existing_device_id: uuid.UUID | None = None,
    ) -> tuple[
        Device,
        list[Camera],
        bool,
        dict[uuid.UUID, set[uuid.UUID]],
    ]:
        existing = (
            session.get(
                Device,
                existing_device_id,
            )
            if existing_device_id is not None
            else self._existing_device(
                session,
                inspection=inspection,
            )
        )
        if (
            existing_device_id is not None
            and (
                existing is None
                or existing.adapter_type != "onvif"
            )
        ):
            raise ApiError(
                status_code=409,
                code="onvif_device_identity_confirmation_invalid",
                message="Confirmed ONVIF device is unavailable.",
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
            capabilities_json=(
                build_onvif_capability_snapshot(
                    inspection
                )
            ),
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
        return device, cameras, False, {}
