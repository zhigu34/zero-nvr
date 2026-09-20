from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.modules.auth.models import SecretRecord

from .models import (
    Camera,
    Device,
    DeviceCredential,
    DeviceEndpoint,
)


@dataclass(frozen=True, slots=True)
class OnvifPtzConnection:
    host: str
    port: int
    username: str = field(repr=False)
    password: str = field(repr=False)
    preferred_profile_tokens: tuple[str, ...] = ()


class CameraPtzService:
    def __init__(self, settings: Settings) -> None:
        self.secret_store = SecretStore(settings)

    @staticmethod
    def _ptz_capability(device: Device) -> bool:
        raw = device.capabilities_json or {}
        services = raw.get("onvif_services")
        if not isinstance(services, list):
            return False
        return any(
            isinstance(item, str)
            and item.strip().upper() == "PTZ"
            for item in services
        )

    @classmethod
    def is_capable(
        cls,
        session: Session,
        camera: Camera,
    ) -> bool:
        if camera.device_id is None:
            return False
        device = session.get(Device, camera.device_id)
        return bool(
            device is not None
            and device.adapter_type == "onvif"
            and device.enabled
            and cls._ptz_capability(device)
        )

    def connection(
        self,
        session: Session,
        camera: Camera,
    ) -> OnvifPtzConnection:
        if camera.device_id is None:
            raise ApiError(
                status_code=409,
                code="camera_ptz_unavailable",
                message="Camera does not have an ONVIF PTZ device.",
            )

        device = session.get(Device, camera.device_id)
        if (
            device is None
            or device.adapter_type != "onvif"
            or not device.enabled
            or not self._ptz_capability(device)
        ):
            raise ApiError(
                status_code=409,
                code="camera_ptz_unavailable",
                message="Camera does not advertise ONVIF PTZ capability.",
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
                code="camera_ptz_unavailable",
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

        secret = session.get(
            SecretRecord,
            credential.secret_ref,
        )
        if secret is None:
            raise ApiError(
                status_code=409,
                code="device_credential_unavailable",
                message="ONVIF device credentials are unavailable.",
            )

        try:
            value = self.secret_store.decrypt_json(
                key_id=secret.key_id,
                ciphertext=secret.encrypted_payload,
                version=secret.version,
            )
        except Exception as exc:
            raise ApiError(
                status_code=409,
                code="device_credential_unavailable",
                message="ONVIF device credentials are unavailable.",
            ) from exc

        username = value.get("username")
        password = value.get("password")
        if not isinstance(username, str) or not isinstance(
            password,
            str,
        ):
            raise ApiError(
                status_code=409,
                code="device_credential_unavailable",
                message="ONVIF device credentials are unavailable.",
            )

        bindings = {
            item.purpose: item.stream_profile_id
            for item in camera.stream_bindings
        }
        profile_by_id = {
            item.id: item
            for item in camera.stream_profiles
        }
        preferred: list[str] = []
        for purpose in (
            "LIVE_HIGH",
            "RECORD",
            "LIVE_LOW",
            "SNAPSHOT",
        ):
            profile_id = bindings.get(purpose)
            profile = (
                profile_by_id.get(profile_id)
                if profile_id is not None
                else None
            )
            if (
                profile is not None
                and profile.adapter_profile_key not in preferred
            ):
                preferred.append(
                    profile.adapter_profile_key
                )

        return OnvifPtzConnection(
            host=endpoint.host,
            port=endpoint.port or 80,
            username=username,
            password=password,
            preferred_profile_tokens=tuple(preferred),
        )
