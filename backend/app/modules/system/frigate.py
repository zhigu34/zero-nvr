from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.modules.cameras.models import Camera

from .models import SystemSetting


FRIGATE_NAMESPACE = "ai.frigate"
_FRIGATE_OWNER_ID = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "zero-nvr/system-setting/ai.frigate",
)


@dataclass(frozen=True, slots=True)
class FrigateCredentials:
    http_bearer_token: str | None = field(
        default=None,
        repr=False,
    )
    http_username: str | None = field(
        default=None,
        repr=False,
    )
    http_password: str | None = field(
        default=None,
        repr=False,
    )
    mqtt_username: str | None = field(
        default=None,
        repr=False,
    )
    mqtt_password: str | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class FrigateProviderConfig:
    enabled: bool
    mode: str
    instance_id: str
    base_url: str
    camera_map: dict[str, uuid.UUID]
    mqtt_enabled: bool
    mqtt_host: str | None
    mqtt_port: int
    mqtt_topic_prefix: str
    mqtt_tls: bool
    credentials: FrigateCredentials = field(
        default_factory=FrigateCredentials,
        repr=False,
    )


class FrigateProviderSettingsService:
    def __init__(self, settings: Settings) -> None:
        self.secret_store = SecretStore(settings)

    @staticmethod
    def _base_url(value: str) -> str:
        normalized = value.strip().rstrip("/")
        try:
            parsed = urlsplit(normalized)
        except ValueError as exc:
            raise ApiError(
                status_code=400,
                code="frigate_url_invalid",
                message="Frigate base URL is invalid.",
            ) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ApiError(
                status_code=400,
                code="frigate_url_invalid",
                message="Frigate base URL must be an http(s) origin/path without embedded credentials.",
            )
        return normalized

    @staticmethod
    def _camera_map(
        session: Session,
        value: dict[str, uuid.UUID],
    ) -> dict[str, uuid.UUID]:
        normalized: dict[str, uuid.UUID] = {}
        for raw_key, camera_id in value.items():
            key = raw_key.strip()
            if (
                not key
                or len(key) > 256
                or "/" in key
                or "\\" in key
            ):
                raise ApiError(
                    status_code=400,
                    code="frigate_camera_key_invalid",
                    message="Frigate camera mapping contains an invalid camera key.",
                )
            if session.get(Camera, camera_id) is None:
                raise ApiError(
                    status_code=400,
                    code="frigate_camera_mapping_unknown",
                    message="Frigate camera mapping references an unknown zero-nvr camera.",
                    details={
                        "frigate_camera": key,
                        "camera_id": str(camera_id),
                    },
                )
            normalized[key] = camera_id
        return normalized

    @staticmethod
    def _mqtt(
        *,
        enabled: bool,
        host: str | None,
        port: int,
        topic_prefix: str,
    ) -> tuple[str | None, int, str]:
        normalized_host = (
            host.strip()
            if isinstance(host, str)
            else None
        )
        if enabled and not normalized_host:
            raise ApiError(
                status_code=400,
                code="frigate_mqtt_host_required",
                message="Frigate MQTT host is required when MQTT ingest is enabled.",
            )
        if port < 1 or port > 65535:
            raise ApiError(
                status_code=400,
                code="frigate_mqtt_port_invalid",
                message="Frigate MQTT port is invalid.",
            )
        prefix = topic_prefix.strip().strip("/")
        if (
            not prefix
            or len(prefix) > 128
            or "+" in prefix
            or "#" in prefix
        ):
            raise ApiError(
                status_code=400,
                code="frigate_mqtt_topic_invalid",
                message="Frigate MQTT topic prefix is invalid.",
            )
        return normalized_host, port, prefix

    def _credentials(
        self,
        session: Session,
        *,
        secret_ref: uuid.UUID | None,
    ) -> FrigateCredentials:
        if secret_ref is None:
            return FrigateCredentials()
        try:
            payload = self.secret_store.read_json(
                session,
                secret_ref,
                kind="frigate_credentials",
                owner_type="system_setting",
                owner_id=_FRIGATE_OWNER_ID,
            )
        except Exception as exc:
            raise ApiError(
                status_code=409,
                code="frigate_credentials_unavailable",
                message="Frigate credentials could not be decrypted.",
            ) from exc

        def optional_text(key: str) -> str | None:
            value = payload.get(key)
            return value if isinstance(value, str) and value else None

        return FrigateCredentials(
            http_bearer_token=optional_text(
                "http_bearer_token"
            ),
            http_username=optional_text("http_username"),
            http_password=optional_text("http_password"),
            mqtt_username=optional_text("mqtt_username"),
            mqtt_password=optional_text("mqtt_password"),
        )

    def get(
        self,
        session: Session,
    ) -> FrigateProviderConfig | None:
        setting = session.get(
            SystemSetting,
            FRIGATE_NAMESPACE,
        )
        if setting is None:
            return None
        value = setting.value_json or {}

        try:
            camera_map = {
                str(key): uuid.UUID(str(camera_id))
                for key, camera_id in dict(
                    value.get("camera_map") or {}
                ).items()
            }
            secret_ref = (
                uuid.UUID(str(value["secret_ref"]))
                if value.get("secret_ref")
                else None
            )
        except (TypeError, ValueError) as exc:
            raise ApiError(
                status_code=409,
                code="frigate_settings_invalid",
                message="Stored Frigate settings are invalid.",
            ) from exc

        return FrigateProviderConfig(
            enabled=bool(value.get("enabled", False)),
            mode=str(value.get("mode") or "external"),
            instance_id=str(value.get("instance_id") or ""),
            base_url=str(value.get("base_url") or ""),
            camera_map=camera_map,
            mqtt_enabled=bool(
                value.get("mqtt_enabled", False)
            ),
            mqtt_host=(
                str(value["mqtt_host"])
                if value.get("mqtt_host")
                else None
            ),
            mqtt_port=int(value.get("mqtt_port", 1883)),
            mqtt_topic_prefix=str(
                value.get("mqtt_topic_prefix") or "frigate"
            ),
            mqtt_tls=bool(value.get("mqtt_tls", False)),
            credentials=self._credentials(
                session,
                secret_ref=secret_ref,
            ),
        )

    def _replace_credentials(
        self,
        session: Session,
        *,
        existing_ref: uuid.UUID | None,
        credentials: FrigateCredentials,
    ) -> uuid.UUID | None:
        payload = {
            key: value
            for key, value in {
                "http_bearer_token": credentials.http_bearer_token,
                "http_username": credentials.http_username,
                "http_password": credentials.http_password,
                "mqtt_username": credentials.mqtt_username,
                "mqtt_password": credentials.mqtt_password,
            }.items()
            if value
        }

        if existing_ref is not None:
            try:
                metadata = self.secret_store.metadata(
                    session,
                    existing_ref,
                )
            except KeyError:
                existing_ref = None
            else:
                if (
                    metadata.kind != "frigate_credentials"
                    or metadata.owner_type != "system_setting"
                    or metadata.owner_id != _FRIGATE_OWNER_ID
                ):
                    raise ApiError(
                        status_code=409,
                        code="frigate_credentials_unavailable",
                        message="Frigate credentials are unavailable.",
                    )

        if not payload:
            if existing_ref is not None:
                self.secret_store.delete(
                    session,
                    existing_ref,
                    kind="frigate_credentials",
                    owner_type="system_setting",
                    owner_id=_FRIGATE_OWNER_ID,
                )
            return None

        if existing_ref is None:
            return self.secret_store.create_json(
                session,
                kind="frigate_credentials",
                owner_type="system_setting",
                owner_id=_FRIGATE_OWNER_ID,
                value=payload,
            )

        self.secret_store.replace_json(
            session,
            existing_ref,
            kind="frigate_credentials",
            owner_type="system_setting",
            owner_id=_FRIGATE_OWNER_ID,
            value=payload,
        )
        return existing_ref

    def put(
        self,
        session: Session,
        *,
        enabled: bool,
        mode: str,
        base_url: str,
        camera_map: dict[str, uuid.UUID],
        mqtt_enabled: bool,
        mqtt_host: str | None,
        mqtt_port: int,
        mqtt_topic_prefix: str,
        mqtt_tls: bool,
        credentials: FrigateCredentials | None = None,
        replace_credentials: bool = False,
    ) -> FrigateProviderConfig:
        if mode not in {"managed", "external"}:
            raise ApiError(
                status_code=400,
                code="frigate_mode_invalid",
                message="Frigate mode must be managed or external.",
            )

        normalized_url = self._base_url(base_url)
        normalized_map = self._camera_map(
            session,
            camera_map,
        )
        host, port, prefix = self._mqtt(
            enabled=mqtt_enabled,
            host=mqtt_host,
            port=mqtt_port,
            topic_prefix=mqtt_topic_prefix,
        )

        setting = session.get(
            SystemSetting,
            FRIGATE_NAMESPACE,
        )
        current = (
            dict(setting.value_json or {})
            if setting is not None
            else {}
        )
        instance_id = str(
            current.get("instance_id")
            or uuid.uuid4().hex
        )

        current_ref: uuid.UUID | None = None
        if current.get("secret_ref"):
            try:
                current_ref = uuid.UUID(
                    str(current["secret_ref"])
                )
            except ValueError:
                current_ref = None

        secret_ref = current_ref
        if replace_credentials:
            secret_ref = self._replace_credentials(
                session,
                existing_ref=current_ref,
                credentials=(
                    credentials
                    or FrigateCredentials()
                ),
            )

        value_json: dict[str, Any] = {
            "enabled": enabled,
            "mode": mode,
            "instance_id": instance_id,
            "base_url": normalized_url,
            "camera_map": {
                key: str(camera_id)
                for key, camera_id in normalized_map.items()
            },
            "mqtt_enabled": mqtt_enabled,
            "mqtt_host": host,
            "mqtt_port": port,
            "mqtt_topic_prefix": prefix,
            "mqtt_tls": mqtt_tls,
        }
        if secret_ref is not None:
            value_json["secret_ref"] = str(secret_ref)

        if setting is None:
            setting = SystemSetting(
                namespace=FRIGATE_NAMESPACE,
                value_json=value_json,
            )
            session.add(setting)
        else:
            setting.value_json = value_json

        session.flush()
        result = self.get(session)
        assert result is not None
        return result
