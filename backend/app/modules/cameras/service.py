from __future__ import annotations

import uuid
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.core.security import SecretStore

from .models import (
    STREAM_PURPOSES,
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    DeviceCredential,
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
        include_retired: bool = False,
    ) -> list[Camera]:
        statement = select(Camera).order_by(Camera.name, Camera.id)
        if not include_retired:
            statement = statement.where(
                Camera.retired_at.is_(None)
            )
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
    def validate_rtsp_url(value: str) -> tuple[str, int]:
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

        profile.stream_uri_ref = self.secret_store.create_json(
            session,
            kind="rtsp_uri",
            owner_type="camera_stream_profile",
            owner_id=profile.id,
            value={"uri": rtsp_url},
        )
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
        primary_host, primary_port = self.validate_rtsp_url(primary_url)
        if secondary_url is not None:
            self.validate_rtsp_url(secondary_url)

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

        try:
            value = self.secret_store.read_json(
                session,
                profile.stream_uri_ref,
                kind="rtsp_uri",
                owner_type="camera_stream_profile",
                owner_id=profile.id,
            )
        except Exception as exc:
            raise ApiError(
                status_code=409,
                code="stream_secret_missing",
                message="Stream credential reference is unavailable.",
            ) from exc
        uri = value.get("uri")
        if not isinstance(uri, str) or not uri:
            raise ApiError(
                status_code=409,
                code="stream_uri_unavailable",
                message="Stream URI is not configured.",
            )

        try:
            parsed = urlsplit(uri)
            existing_username = parsed.username
        except ValueError as exc:
            raise ApiError(
                status_code=409,
                code="stream_uri_invalid",
                message="Stream URI is invalid.",
            ) from exc

        # Manual RTSP URLs may already contain their own authentication.
        if existing_username is not None:
            return uri

        camera = session.get(Camera, profile.camera_id)
        if camera is None or camera.device_id is None:
            return uri

        device = session.get(Device, camera.device_id)
        if device is None or device.adapter_type != "onvif":
            return uri

        credential = session.scalar(
            select(DeviceCredential).where(
                DeviceCredential.device_id == device.id,
                DeviceCredential.kind == "onvif",
            )
        )
        if credential is None:
            raise ApiError(
                status_code=409,
                code="device_credential_unavailable",
                message="ONVIF device credentials are unavailable.",
            )

        try:
            credential_value = self.secret_store.read_json(
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

        username = credential_value.get("username")
        password = credential_value.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise ApiError(
                status_code=409,
                code="device_credential_unavailable",
                message="ONVIF device credentials are unavailable.",
            )

        if not username and not password:
            return uri

        host = parsed.hostname
        if not host:
            raise ApiError(
                status_code=409,
                code="stream_uri_invalid",
                message="Stream URI is invalid.",
            )

        display_host = (
            f"[{host}]"
            if ":" in host and not host.startswith("[")
            else host
        )
        try:
            port = parsed.port
        except ValueError as exc:
            raise ApiError(
                status_code=409,
                code="stream_uri_invalid",
                message="Stream URI is invalid.",
            ) from exc

        host_port = display_host
        if port is not None:
            host_port = f"{display_host}:{port}"

        auth = (
            f"{quote(username, safe='')}:{quote(password, safe='')}@"
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
        if enabled and camera.retired_at is not None:
            raise ApiError(
                status_code=409,
                code="camera_retired",
                message="Retired camera must be restored before it can be enabled.",
            )
        camera.enabled = enabled
        session.flush()
        return camera

    @staticmethod
    def set_retired(
        session: Session,
        *,
        camera: Camera,
        retired: bool,
    ) -> Camera:
        if retired:
            if camera.retired_at is None:
                camera.retired_at = utc_now()
            camera.enabled = False
        elif camera.retired_at is not None:
            camera.retired_at = None
            # Restore to inventory only. Explicit enable is a separate action
            # so restoring a camera can never unexpectedly start media pulls.
            camera.enabled = False
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
