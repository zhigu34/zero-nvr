from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.integrations.zlm import ZlmAdapter

from .models import Camera, CameraStreamProfile
from .service import CameraService


@dataclass(frozen=True, slots=True)
class ZlmStreamReference:
    camera_id: uuid.UUID
    profile_id: uuid.UUID
    app: str
    stream: str


@dataclass(frozen=True, slots=True)
class DesiredZlmStream:
    camera_id: uuid.UUID
    profile_id: uuid.UUID
    app: str
    stream: str
    source_uri: str = field(repr=False)

    @property
    def reference(self) -> ZlmStreamReference:
        return ZlmStreamReference(
            camera_id=self.camera_id,
            profile_id=self.profile_id,
            app=self.app,
            stream=self.stream,
        )


class CameraMediaRuntimeService:
    """Translate persisted camera intent into thin ZLM runtime operations.

    Database reads and external ZLM calls are deliberately separated. Callers
    should finish/commit their DB transaction after desired_streams() and only
    then invoke ensure_streams()/stop_streams().
    """

    app_name = "zero-nvr"

    def __init__(
        self,
        settings: Settings,
        *,
        zlm_factory: Callable[[Settings], Any] = ZlmAdapter,
    ) -> None:
        self.settings = settings
        self._zlm_factory = zlm_factory
        self._camera_service = CameraService(settings)

    @classmethod
    def reference_for(
        cls,
        *,
        camera_id: uuid.UUID,
        profile_id: uuid.UUID,
    ) -> ZlmStreamReference:
        return ZlmStreamReference(
            camera_id=camera_id,
            profile_id=profile_id,
            app=cls.app_name,
            stream=f"profile-{profile_id.hex}",
        )

    def desired_streams(
        self,
        session: Session,
        *,
        camera: Camera,
    ) -> list[DesiredZlmStream]:
        if not camera.enabled:
            return []

        profile_ids = {
            binding.stream_profile_id
            for binding in camera.stream_bindings
        }
        if not profile_ids:
            return []

        profiles = list(
            session.scalars(
                select(CameraStreamProfile)
                .where(
                    CameraStreamProfile.camera_id == camera.id,
                    CameraStreamProfile.id.in_(profile_ids),
                )
                .order_by(CameraStreamProfile.id)
            )
        )
        found = {profile.id for profile in profiles}
        missing = profile_ids - found
        if missing:
            raise ApiError(
                status_code=409,
                code="camera_stream_binding_invalid",
                message="Camera stream binding references a missing profile.",
            )

        desired: list[DesiredZlmStream] = []
        for profile in profiles:
            reference = self.reference_for(
                camera_id=camera.id,
                profile_id=profile.id,
            )
            desired.append(
                DesiredZlmStream(
                    camera_id=camera.id,
                    profile_id=profile.id,
                    app=reference.app,
                    stream=reference.stream,
                    source_uri=self._camera_service.resolve_stream_uri(
                        session,
                        profile,
                    ),
                )
            )

        return desired

    @classmethod
    def stream_references(
        cls,
        *,
        camera: Camera,
    ) -> list[ZlmStreamReference]:
        profile_ids = sorted(
            {
                binding.stream_profile_id
                for binding in camera.stream_bindings
            },
            key=str,
        )
        return [
            cls.reference_for(
                camera_id=camera.id,
                profile_id=profile_id,
            )
            for profile_id in profile_ids
        ]

    def ensure_streams(
        self,
        desired: list[DesiredZlmStream],
    ) -> list[ZlmStreamReference]:
        if not desired:
            return []

        references: list[ZlmStreamReference] = []
        with self._zlm_factory(self.settings) as zlm:
            for item in desired:
                if not zlm.is_media_online(
                    app=item.app,
                    stream=item.stream,
                ):
                    zlm.add_stream_proxy(
                        app=item.app,
                        stream=item.stream,
                        source_url=item.source_uri,
                        enable_mp4=False,
                        enable_hls=True,
                        retry_count=-1,
                    )
                references.append(item.reference)
        return references

    def internal_rtsp_url(self, reference: ZlmStreamReference) -> str:
        base = self.settings.zlm_rtsp_base_url.rstrip("/")
        app = quote(reference.app, safe="")
        stream = quote(reference.stream, safe="")
        return f"{base}/{app}/{stream}"

    def public_hls_url(self, reference: ZlmStreamReference) -> str:
        base = self.settings.zlm_public_base_url.rstrip("/")
        app = quote(reference.app, safe="")
        stream = quote(reference.stream, safe="")
        return f"{base}/{app}/{stream}/hls.m3u8"

    def stop_streams(
        self,
        references: list[ZlmStreamReference],
    ) -> None:
        if not references:
            return

        with self._zlm_factory(self.settings) as zlm:
            for item in references:
                if zlm.is_media_online(
                    app=item.app,
                    stream=item.stream,
                ):
                    zlm.close_stream(
                        app=item.app,
                        stream=item.stream,
                        force=True,
                    )
