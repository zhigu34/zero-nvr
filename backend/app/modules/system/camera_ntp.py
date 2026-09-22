from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.modules.cameras.models import (
    Camera,
    Device,
    DeviceCredential,
    DeviceEndpoint,
)


@dataclass(frozen=True, slots=True)
class OnvifNtpTarget:
    device_id: uuid.UUID
    name: str
    host: str
    port: int
    username: str = field(repr=False)
    password: str = field(repr=False)


class CameraNtpService:
    def __init__(self, settings: Settings) -> None:
        self.secret_store = SecretStore(settings)

    @staticmethod
    def effective_mode(
        session: Session,
        device_id: uuid.UUID,
    ) -> str:
        modes = set(
            session.scalars(
                select(
                    Camera.time_sync_mode
                ).where(
                    Camera.device_id
                    == device_id,
                    Camera.retired_at.is_(
                        None
                    ),
                )
            )
        )
        if "manage_ntp" in modes:
            return "manage_ntp"
        if "monitor" in modes:
            return "monitor"
        return "ignore"

    @classmethod
    def list_devices(
        cls,
        session: Session,
        *,
        modes: set[str] | None = None,
    ) -> list[Device]:
        devices = list(
            session.scalars(
                select(Device)
                .where(
                    Device.adapter_type == "onvif",
                    Device.enabled.is_(True),
                )
                .order_by(
                    Device.name,
                    Device.id,
                )
            )
        )
        if modes is None:
            return devices
        return [
            device
            for device in devices
            if cls.effective_mode(
                session,
                device.id,
            )
            in modes
        ]

    def target(
        self,
        session: Session,
        device: Device,
    ) -> OnvifNtpTarget:
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
                code="onvif_endpoint_unavailable",
                message="ONVIF device endpoint is unavailable.",
            )

        credential = session.scalar(
            select(DeviceCredential)
            .where(
                DeviceCredential.device_id == device.id,
                DeviceCredential.kind == "onvif",
                DeviceCredential.endpoint_id == endpoint.id,
            )
            .limit(1)
        )
        if credential is None:
            credential = session.scalar(
                select(DeviceCredential)
                .where(
                    DeviceCredential.device_id == device.id,
                    DeviceCredential.kind == "onvif",
                )
                .order_by(DeviceCredential.id)
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
        if not isinstance(username, str) or not isinstance(
            password,
            str,
        ):
            raise ApiError(
                status_code=409,
                code="device_credential_unavailable",
                message="ONVIF device credentials are unavailable.",
            )

        return OnvifNtpTarget(
            device_id=device.id,
            name=device.name,
            host=endpoint.host,
            port=endpoint.port or 80,
            username=username,
            password=password,
        )
