from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any
import uuid

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.cameras.media_runtime import (
    CameraMediaRuntimeService,
    DesiredZlmStream,
)
from app.modules.cameras.models import (
    Camera,
    CameraStreamBinding,
    CameraStreamProfile,
)
from app.modules.cameras.service import CameraService
from app.modules.system.frigate import FrigateProviderConfig


@dataclass(frozen=True, slots=True)
class ManagedFrigatePlan:
    config: dict[str, Any]
    yaml_text: str
    desired_streams: tuple[DesiredZlmStream, ...]
    environment: dict[str, str] = field(
        default_factory=dict,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class ManagedFrigateArtifacts:
    config_path: Path
    environment_path: Path


class ManagedFrigateConfigService:
    """Generate Frigate config from zero-nvr product facts.

    The generated YAML is an output artifact only. It is never read back as
    product source of truth.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.camera_service = CameraService(settings)

    def _camera(
        self,
        session: Session,
        *,
        frigate_key: str,
        camera_id,
    ) -> tuple[dict[str, Any], DesiredZlmStream | None]:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise ApiError(
                status_code=409,
                code="frigate_camera_mapping_unknown",
                message="Managed Frigate camera mapping references a missing camera.",
            )

        binding = session.scalar(
            select(CameraStreamBinding).where(
                CameraStreamBinding.camera_id == camera.id,
                CameraStreamBinding.purpose == "AI_DETECT",
            )
        )
        if binding is None:
            raise ApiError(
                status_code=409,
                code="frigate_ai_stream_binding_missing",
                message="Managed Frigate camera has no AI_DETECT stream binding.",
                details={
                    "frigate_camera": frigate_key,
                    "camera_id": str(camera.id),
                },
            )

        profile = session.get(
            CameraStreamProfile,
            binding.stream_profile_id,
        )
        if (
            profile is None
            or profile.camera_id != camera.id
        ):
            raise ApiError(
                status_code=409,
                code="frigate_ai_stream_binding_invalid",
                message="Managed Frigate AI_DETECT stream binding is invalid.",
            )

        reference = CameraMediaRuntimeService.reference_for(
            camera_id=camera.id,
            profile_id=profile.id,
        )
        zlm_path = (
            f"{self.settings.zlm_rtsp_base_url}/"
            f"{reference.app}/{reference.stream}"
        )

        detect: dict[str, Any] = {
            "enabled": bool(camera.enabled),
            "fps": (
                max(
                    1,
                    min(5, int(round(profile.fps))),
                )
                if profile.fps is not None
                and profile.fps > 0
                else 5
            ),
        }
        if profile.width is not None:
            detect["width"] = profile.width
        if profile.height is not None:
            detect["height"] = profile.height

        camera_config: dict[str, Any] = {
            "enabled": bool(camera.enabled),
            "ffmpeg": {
                "inputs": [
                    {
                        "path": zlm_path,
                        "input_args": "preset-rtsp-generic",
                        "roles": ["detect"],
                    }
                ]
            },
            "detect": detect,
            # Frigate is an AI capability provider, never the recording
            # authority in zero-nvr.
            "record": {"enabled": False},
            "snapshots": {"enabled": True},
        }

        desired: DesiredZlmStream | None = None
        if camera.enabled:
            desired = DesiredZlmStream(
                camera_id=camera.id,
                profile_id=profile.id,
                app=reference.app,
                stream=reference.stream,
                source_uri=self.camera_service.resolve_stream_uri(
                    session,
                    profile,
                ),
            )

        return camera_config, desired

    def build(
        self,
        session: Session,
        *,
        provider: FrigateProviderConfig,
    ) -> ManagedFrigatePlan:
        if provider.mode != "managed":
            raise ApiError(
                status_code=409,
                code="frigate_not_managed",
                message="Managed Frigate config is unavailable in external mode.",
            )
        if not provider.camera_map:
            raise ApiError(
                status_code=409,
                code="frigate_camera_mapping_empty",
                message="Managed Frigate requires at least one camera mapping.",
            )

        config: dict[str, Any] = {
            "record": {"enabled": False},
            "cameras": {},
        }
        environment: dict[str, str] = {}

        if provider.mqtt_enabled:
            if provider.mqtt_host is None:
                raise ApiError(
                    status_code=409,
                    code="frigate_mqtt_host_required",
                    message="Managed Frigate MQTT host is unavailable.",
                )

            mqtt_config: dict[str, Any] = {
                "enabled": True,
                "host": "{FRIGATE_MQTT_HOST}",
                "port": provider.mqtt_port,
                "topic_prefix": provider.mqtt_topic_prefix,
                "client_id": (
                    "frigate-zero-nvr-"
                    f"{provider.instance_id[:12]}"
                ),
                "qos": 1,
            }
            environment["FRIGATE_MQTT_HOST"] = (
                provider.mqtt_host
            )

            credentials = provider.credentials
            if credentials.mqtt_username is not None:
                mqtt_config["user"] = (
                    "{FRIGATE_MQTT_USER}"
                )
                environment["FRIGATE_MQTT_USER"] = (
                    credentials.mqtt_username
                )
            if credentials.mqtt_password is not None:
                mqtt_config["password"] = (
                    "{FRIGATE_MQTT_PASSWORD}"
                )
                environment["FRIGATE_MQTT_PASSWORD"] = (
                    credentials.mqtt_password
                )
            if provider.mqtt_tls:
                # Frigate's container image carries the system CA bundle.
                mqtt_config["tls_ca_certs"] = (
                    "/etc/ssl/certs/ca-certificates.crt"
                )
                mqtt_config["tls_insecure"] = False

            config["mqtt"] = mqtt_config
        else:
            config["mqtt"] = {"enabled": False}

        desired_streams: list[DesiredZlmStream] = []
        cameras: dict[str, Any] = {}
        for frigate_key, camera_id in sorted(
            provider.camera_map.items()
        ):
            camera_config, desired = self._camera(
                session,
                frigate_key=frigate_key,
                camera_id=camera_id,
            )
            cameras[frigate_key] = camera_config
            if desired is not None:
                desired_streams.append(desired)

        config["cameras"] = cameras
        yaml_text = yaml.safe_dump(
            config,
            sort_keys=False,
            allow_unicode=True,
        )

        # Defense-in-depth: generated YAML must never contain provider secrets.
        for secret in (
            provider.credentials.mqtt_username,
            provider.credentials.mqtt_password,
            provider.credentials.http_bearer_token,
            provider.credentials.http_password,
        ):
            if secret and secret in yaml_text:
                raise ApiError(
                    status_code=500,
                    code="frigate_generated_config_secret_leak",
                    message="Managed Frigate config rendering failed safety validation.",
                )

        return ManagedFrigatePlan(
            config=config,
            yaml_text=yaml_text,
            desired_streams=tuple(desired_streams),
            environment=environment,
        )



    @staticmethod
    def _atomic_write(
        path: Path,
        content: str,
        *,
        mode: int,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        temporary = path.with_name(
            f".{path.name}.{uuid.uuid4().hex}.tmp"
        )
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL,
            mode,
        )
        try:
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def persist(
        self,
        plan: ManagedFrigatePlan,
    ) -> ManagedFrigateArtifacts:
        directory = (
            self.settings.data_dir
            / "managed"
            / "frigate"
        )
        config_path = directory / "config.yml"
        environment_path = directory / "runtime.env"

        environment_text = "".join(
            (
                f"{key}="
                + json.dumps(
                    value,
                    ensure_ascii=False,
                )
                + "\n"
            )
            for key, value in sorted(
                plan.environment.items()
            )
        )

        self._atomic_write(
            config_path,
            plan.yaml_text,
            mode=0o640,
        )
        self._atomic_write(
            environment_path,
            environment_text,
            mode=0o600,
        )
        return ManagedFrigateArtifacts(
            config_path=config_path,
            environment_path=environment_path,
        )
