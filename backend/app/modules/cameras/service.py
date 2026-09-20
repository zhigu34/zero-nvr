from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.modules.auth.models import SecretRecord

from .models import (
    STREAM_PURPOSES,
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    DeviceEndpoint,
)


class CameraService:
    def __init__(self, settings: Settings) -> None:
        self.secret_store = SecretStore(settings)

    @staticmethod
    def list_cameras(
        session: Session,
        *,
        allowed_camera_ids: frozenset[uuid.UUID] | None,
    ) -> list[Camera]:
        statement = select(Camera).order_by(Camera.name, Camera.id)
        if allowed_camera_ids is not None:
            if not allowed_camera_ids:
                return []
            statement = statement.where(Camera.id.in_(allowed_camera_ids))
        return list(session.scalars(statement))

    @staticmethod
    def get_camera(session: Session, camera_id: uuid.UUID) -> Camera:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise ApiError(
                status_code=404,
                code="camera_not_found",
                message="Camera was not found.",
            )
        return camera

    @staticmethod
    def _parse_rtsp_url(value: str) -> tuple[str, int]:
        try:
            parsed = urlsplit(value)
            port = parsed.port or 554
        except ValueError as exc:
            raise ApiError(
                status_code=400,
                code="invalid_rtsp_url",
                message="RTSP URL is invalid.",
            ) from exc

        if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
            raise ApiError(
                status_code=400,
                code="invalid_rtsp_url",
                message="RTSP URL must use rtsp:// and include a host.",
            )
        return parsed.hostname, port

    def _create_stream_profile(
        self,
        session: Session,
        *,
        camera: Camera,
        key: str,
        name: str,
        rtsp_url: str,
    ) -> CameraStreamProfile:
        profile = CameraStreamProfile(
            camera_id=camera.id,
            adapter_profile_key=key,
            name=name,
            status="configured",
        )
        session.add(profile)
        session.flush()

        encrypted = self.secret_store.encrypt_json({"uri": rtsp_url})
        secret = SecretRecord(
            kind="rtsp_uri",
            owner_type="camera_stream_profile",
            owner_id=profile.id,
            key_id=encrypted.key_id,
            encrypted_payload=encrypted.ciphertext,
            version=encrypted.version,
        )
        session.add(secret)
        session.flush()
        profile.stream_uri_ref = secret.id
        return profile

    def create_manual_rtsp_camera(
        self,
        session: Session,
        *,
        name: str,
        location: str | None,
        storage_label: str | None,
        primary_name: str,
        primary_url: str,
        secondary_name: str | None,
        secondary_url: str | None,
    ) -> Camera:
        primary_host, primary_port = self._parse_rtsp_url(primary_url)
        if secondary_url is not None:
            self._parse_rtsp_url(secondary_url)

        device = Device(
            name=name,
            adapter_type="manual_rtsp",
            enabled=True,
            capabilities_json={},
        )
        session.add(device)
        session.flush()

        session.add(
            DeviceEndpoint(
                device_id=device.id,
                type="rtsp",
                host=primary_host,
                port=primary_port,
                scheme="rtsp",
                # Do not persist URI path/query here; they may themselves carry
                # tokens. The complete source URI is encrypted in SecretRecord.
                path=None,
                priority=100,
                enabled=True,
                metadata_json={},
            )
        )

        camera = Camera(
            device_id=device.id,
            channel_key="manual-0",
            name=name,
            enabled=True,
            location=location,
            storage_label=storage_label,
        )
        session.add(camera)
        session.flush()

        primary = self._create_stream_profile(
            session,
            camera=camera,
            key="manual-primary",
            name=primary_name,
            rtsp_url=primary_url,
        )

        secondary = None
        if secondary_url is not None and secondary_name is not None:
            secondary = self._create_stream_profile(
                session,
                camera=camera,
                key="manual-secondary",
                name=secondary_name,
                rtsp_url=secondary_url,
            )

        low_profile = secondary or primary
        defaults = {
            "RECORD": primary,
            "LIVE_HIGH": primary,
            "LIVE_LOW": low_profile,
            "AI_DETECT": low_profile,
            "SNAPSHOT": primary,
        }
        session.add_all(
            [
                CameraStreamBinding(
                    camera_id=camera.id,
                    purpose=purpose,
                    stream_profile_id=profile.id,
                    selection_mode="auto",
                )
                for purpose, profile in defaults.items()
            ]
        )
        session.flush()
        return camera

    def resolve_stream_uri(
        self,
        session: Session,
        profile: CameraStreamProfile,
    ) -> str:
        if profile.stream_uri_ref is None:
            raise ApiError(
                status_code=409,
                code="stream_uri_unavailable",
                message="Stream URI is not configured.",
            )

        secret = session.get(SecretRecord, profile.stream_uri_ref)
        if secret is None:
            raise ApiError(
                status_code=409,
                code="stream_secret_missing",
                message="Stream credential reference is unavailable.",
            )

        value = self.secret_store.decrypt_json(
            key_id=secret.key_id,
            ciphertext=secret.encrypted_payload,
            version=secret.version,
        )
        uri = value.get("uri")
        if not isinstance(uri, str) or not uri:
            raise ApiError(
                status_code=409,
                code="stream_uri_unavailable",
                message="Stream URI is not configured.",
            )
        return uri

    @staticmethod
    def update_camera(
        session: Session,
        *,
        camera: Camera,
        changes: dict[str, object],
    ) -> Camera:
        for field in ("name", "location", "storage_label"):
            if field in changes:
                setattr(camera, field, changes[field])
        session.flush()
        return camera

    @staticmethod
    def set_enabled(
        session: Session,
        *,
        camera: Camera,
        enabled: bool,
    ) -> Camera:
        camera.enabled = enabled
        session.flush()
        return camera

    @staticmethod
    def replace_bindings(
        session: Session,
        *,
        camera: Camera,
        bindings: list[tuple[str, uuid.UUID, str]],
    ) -> list[CameraStreamBinding]:
        purposes = [purpose for purpose, _profile_id, _mode in bindings]
        if len(purposes) != len(set(purposes)):
            raise ApiError(
                status_code=400,
                code="duplicate_stream_purpose",
                message="Each stream purpose may be configured only once.",
            )
        unknown = set(purposes) - set(STREAM_PURPOSES)
        if unknown:
            raise ApiError(
                status_code=400,
                code="invalid_stream_purpose",
                message="One or more stream purposes are invalid.",
            )

        profile_ids = {profile_id for _purpose, profile_id, _mode in bindings}
        profiles = list(
            session.scalars(
                select(CameraStreamProfile).where(
                    CameraStreamProfile.id.in_(profile_ids),
                    CameraStreamProfile.camera_id == camera.id,
                )
            )
        ) if profile_ids else []
        found = {profile.id for profile in profiles}
        missing = profile_ids - found
        if missing:
            raise ApiError(
                status_code=400,
                code="invalid_stream_profile",
                message="A selected stream profile does not belong to this camera.",
            )

        session.execute(
            delete(CameraStreamBinding).where(
                CameraStreamBinding.camera_id == camera.id
            )
        )
        result = [
            CameraStreamBinding(
                camera_id=camera.id,
                purpose=purpose,
                stream_profile_id=profile_id,
                selection_mode=mode,
            )
            for purpose, profile_id, mode in bindings
        ]
        session.add_all(result)
        session.flush()
        return result
