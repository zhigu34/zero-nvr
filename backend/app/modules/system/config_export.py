from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.alerts.models import AlertPolicy
from app.modules.auth.camera_scope import CameraScopeService
from app.modules.auth.models import Role
from app.modules.auth.oidc import OidcProviderSettingsService
from app.modules.backups.models import BackupPolicy
from app.modules.cameras.models import (
    Camera,
    CameraGroup,
    CameraGroupMember,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    DeviceCredential,
    DeviceEndpoint,
)
from app.modules.notifications.models import NotificationTarget
from app.modules.recordings.models import RecordingPolicy, RetentionPolicy
from app.modules.storage.models import StorageTarget

from .frigate import FRIGATE_NAMESPACE
from .models import SystemSetting
from .settings import SystemSettingsService, TimeSystemSettingsService


def _uuid(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


class ConfigurationExportService:
    FORMAT = "zero-nvr.configuration"
    VERSION = 1

    @staticmethod
    def _general(
        session: Session,
        settings: Settings,
    ) -> dict[str, object]:
        value = SystemSettingsService.get(
            session,
            settings=settings,
        )
        time_settings = (
            TimeSystemSettingsService.get(
                session
            )
        )
        return {
            "system_name": value.system_name,
            # Compatibility aliases retained in configuration
            # format v1; the canonical values live in "time".
            "display_timezone": (
                time_settings.recording_timezone
            ),
            "camera_ntp_servers": list(
                time_settings.managed_camera_ntp_servers
            ),
        }

    @staticmethod
    def _time_settings(
        session: Session,
    ) -> dict[str, object]:
        value = TimeSystemSettingsService.get(
            session
        )
        return {
            "recording_timezone": (
                value.recording_timezone
            ),
            "managed_camera_ntp_mode": (
                value.managed_camera_ntp_mode
            ),
            "managed_camera_ntp_servers": list(
                value.managed_camera_ntp_servers
            ),
        }

    @staticmethod
    def _roles(
        session: Session,
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        roles = list(
            session.scalars(
                select(Role).order_by(
                    Role.name,
                    Role.id,
                )
            )
        )
        for role in roles:
            scope = CameraScopeService.get_scope(
                session,
                principal_type="role",
                principal_id=role.id,
            )
            result.append(
                {
                    "id": str(role.id),
                    "name": role.name,
                    "description": role.description,
                    "built_in": role.built_in,
                    "permissions": sorted(
                        item.permission
                        for item in role.permissions
                    ),
                    "camera_scope": (
                        {
                            "mode": scope.mode,
                            "camera_ids": [
                                str(item)
                                for item in scope.camera_ids
                            ],
                            "camera_group_ids": [
                                str(item)
                                for item
                                in scope.camera_group_ids
                            ],
                        }
                        if scope is not None
                        else None
                    ),
                }
            )
        return result

    @staticmethod
    def _devices(
        session: Session,
    ) -> dict[str, list[dict[str, object]]]:
        devices = [
            {
                "id": str(item.id),
                "name": item.name,
                "manufacturer": item.manufacturer,
                "model": item.model,
                "serial_number": item.serial_number,
                "hardware_id": item.hardware_id,
                "adapter_type": item.adapter_type,
                "enabled": item.enabled,
                "capabilities": (
                    item.capabilities_json or {}
                ),
            }
            for item in session.scalars(
                select(Device).order_by(
                    Device.name,
                    Device.id,
                )
            )
        ]
        endpoints = [
            {
                "id": str(item.id),
                "device_id": str(item.device_id),
                "type": item.type,
                "host": item.host,
                "port": item.port,
                "scheme": item.scheme,
                "path": item.path,
                "priority": item.priority,
                "enabled": item.enabled,
            }
            for item in session.scalars(
                select(DeviceEndpoint).order_by(
                    DeviceEndpoint.device_id,
                    DeviceEndpoint.priority,
                    DeviceEndpoint.id,
                )
            )
        ]
        credentials = [
            {
                "device_id": str(item.device_id),
                "endpoint_id": _uuid(
                    item.endpoint_id
                ),
                "kind": item.kind,
                "credentials_configured": True,
            }
            for item in session.scalars(
                select(DeviceCredential).order_by(
                    DeviceCredential.device_id,
                    DeviceCredential.kind,
                    DeviceCredential.id,
                )
            )
        ]
        return {
            "devices": devices,
            "endpoints": endpoints,
            "credentials": credentials,
        }

    @staticmethod
    def _cameras(
        session: Session,
    ) -> dict[str, list[dict[str, object]]]:
        cameras = [
            {
                "id": str(item.id),
                "device_id": _uuid(item.device_id),
                "channel_key": item.channel_key,
                "name": item.name,
                "enabled": item.enabled,
                "retired_at": _time(
                    item.retired_at
                ),
                "location": item.location,
                "storage_label": (
                    item.storage_label
                ),
            }
            for item in session.scalars(
                select(Camera).order_by(
                    Camera.name,
                    Camera.id,
                )
            )
        ]
        profiles = [
            {
                "id": str(item.id),
                "camera_id": str(item.camera_id),
                "adapter_profile_key": (
                    item.adapter_profile_key
                ),
                "video_source_key": (
                    item.video_source_key
                ),
                "name": item.name,
                "codec": item.codec,
                "width": item.width,
                "height": item.height,
                "fps": item.fps,
                "bitrate_kbps": (
                    item.bitrate_kbps
                ),
                "bitrate_mode": (
                    item.bitrate_mode
                ),
                "gop_seconds": item.gop_seconds,
                "audio_codec": (
                    item.audio_codec
                ),
                "has_audio": item.has_audio,
                "status": item.status,
                "stream_uri_configured": (
                    item.stream_uri_ref
                    is not None
                ),
            }
            for item in session.scalars(
                select(
                    CameraStreamProfile
                ).order_by(
                    CameraStreamProfile.camera_id,
                    CameraStreamProfile.id,
                )
            )
        ]
        bindings = [
            {
                "id": str(item.id),
                "camera_id": str(item.camera_id),
                "purpose": item.purpose,
                "stream_profile_id": str(
                    item.stream_profile_id
                ),
                "selection_mode": (
                    item.selection_mode
                ),
            }
            for item in session.scalars(
                select(
                    CameraStreamBinding
                ).order_by(
                    CameraStreamBinding.camera_id,
                    CameraStreamBinding.purpose,
                )
            )
        ]
        groups = [
            {
                "id": str(item.id),
                "name": item.name,
                "description": item.description,
                "parent_id": _uuid(
                    item.parent_id
                ),
            }
            for item in session.scalars(
                select(CameraGroup).order_by(
                    CameraGroup.name,
                    CameraGroup.id,
                )
            )
        ]
        members = [
            {
                "camera_group_id": str(
                    row.camera_group_id
                ),
                "camera_id": str(
                    row.camera_id
                ),
            }
            for row in session.scalars(
                select(
                    CameraGroupMember
                ).order_by(
                    CameraGroupMember.camera_group_id,
                    CameraGroupMember.camera_id,
                )
            )
        ]
        return {
            "cameras": cameras,
            "stream_profiles": profiles,
            "stream_bindings": bindings,
            "groups": groups,
            "group_members": members,
        }

    @staticmethod
    def _recording(
        session: Session,
    ) -> dict[str, list[dict[str, object]]]:
        policies = [
            {
                "id": str(item.id),
                "camera_id": str(item.camera_id),
                "baseline_mode": (
                    item.baseline_mode
                ),
                "schedule": (
                    item.schedule_json or {}
                ),
                "schedule_timezone": (
                    item.schedule_timezone
                ),
                "event_recording_enabled": (
                    item.event_recording_enabled
                ),
                "event_filter": (
                    item.event_filter_json or {}
                ),
                "segment_target_seconds": (
                    item.segment_target_seconds
                ),
                "pre_roll_seconds": (
                    item.pre_roll_seconds
                ),
                "post_roll_seconds": (
                    item.post_roll_seconds
                ),
                "storage_target_id": _uuid(
                    item.storage_target_id
                ),
                "retention_policy_id": _uuid(
                    item.retention_policy_id
                ),
                "enabled": item.enabled,
            }
            for item in session.scalars(
                select(
                    RecordingPolicy
                ).order_by(
                    RecordingPolicy.camera_id
                )
            )
        ]
        retention = [
            {
                "id": str(item.id),
                "name": item.name,
                "scope_type": (
                    item.scope_type
                ),
                "scope_id": _uuid(
                    item.scope_id
                ),
                "ordinary_keep_days": (
                    item.ordinary_keep_days
                ),
                "event_keep_days": (
                    item.event_keep_days
                ),
                "manual_keep_days": (
                    item.manual_keep_days
                ),
                "mode": item.mode,
                "require_archive_before_delete": (
                    item.require_archive_before_delete
                ),
                "enabled": item.enabled,
            }
            for item in session.scalars(
                select(
                    RetentionPolicy
                ).order_by(
                    RetentionPolicy.name,
                    RetentionPolicy.id,
                )
            )
        ]
        return {
            "policies": policies,
            "retention_policies": retention,
        }

    @staticmethod
    def _storage(
        session: Session,
    ) -> list[dict[str, object]]:
        return [
            {
                "id": str(item.id),
                "type": item.type,
                "role": item.role,
                "name": item.name,
                "enabled": item.enabled,
                "config": item.config_json or {},
                "credentials_configured": (
                    item.credential_secret_ref
                    is not None
                ),
            }
            for item in session.scalars(
                select(StorageTarget).order_by(
                    StorageTarget.name,
                    StorageTarget.id,
                )
            )
        ]

    @staticmethod
    def _alerts(
        session: Session,
    ) -> list[dict[str, object]]:
        return [
            {
                "id": str(item.id),
                "name": item.name,
                "enabled": item.enabled,
                "severity": item.severity,
                "match": item.match_json or {},
                "action": item.action_json or {},
                "cooldown_seconds": (
                    item.cooldown_seconds
                ),
            }
            for item in session.scalars(
                select(AlertPolicy).order_by(
                    AlertPolicy.name,
                    AlertPolicy.id,
                )
            )
        ]

    @staticmethod
    def _notifications(
        session: Session,
    ) -> list[dict[str, object]]:
        return [
            {
                "id": str(item.id),
                "name": item.name,
                "kind": item.kind,
                "enabled": item.enabled,
                "config": item.config_json or {},
                "url_configured": (
                    item.kind == "apprise"
                    and bool(item.secret_ref)
                ),
                "credentials_configured": (
                    item.kind == "smtp"
                    and bool(item.secret_ref)
                ),
            }
            for item in session.scalars(
                select(
                    NotificationTarget
                ).order_by(
                    NotificationTarget.name,
                    NotificationTarget.id,
                )
            )
        ]

    @staticmethod
    def _oidc(
        session: Session,
    ) -> list[dict[str, object]]:
        return [
            {
                "id": str(item.id),
                "key": item.key,
                "name": item.name,
                "enabled": item.enabled,
                "issuer": item.issuer,
                "client_id": item.client_id,
                "client_secret_configured": (
                    item.secret_ref
                    is not None
                ),
                "auto_provision": (
                    item.auto_provision
                ),
                "email_linking": (
                    item.email_linking
                ),
                "default_role_ids": [
                    str(role_id)
                    for role_id
                    in item.default_role_ids
                ],
            }
            for item in (
                OidcProviderSettingsService.list(
                    session
                )
            )
        ]

    @staticmethod
    def _frigate(
        session: Session,
    ) -> dict[str, object] | None:
        row = session.get(
            SystemSetting,
            FRIGATE_NAMESPACE,
        )
        if row is None:
            return None
        value = dict(row.value_json or {})
        return {
            "enabled": bool(
                value.get("enabled", False)
            ),
            "mode": str(
                value.get("mode")
                or "external"
            ),
            "instance_id": str(
                value.get("instance_id")
                or ""
            ),
            "base_url": str(
                value.get("base_url")
                or ""
            ),
            "camera_map": dict(
                value.get("camera_map")
                or {}
            ),
            "mqtt_enabled": bool(
                value.get(
                    "mqtt_enabled",
                    False,
                )
            ),
            "mqtt_host": (
                str(value["mqtt_host"])
                if value.get("mqtt_host")
                else None
            ),
            "mqtt_port": int(
                value.get("mqtt_port", 1883)
            ),
            "mqtt_topic_prefix": str(
                value.get(
                    "mqtt_topic_prefix",
                    "frigate",
                )
            ),
            "mqtt_tls": bool(
                value.get("mqtt_tls", False)
            ),
            "credentials_configured": bool(
                value.get("secret_ref")
            ),
        }

    @staticmethod
    def _backups(
        session: Session,
    ) -> list[dict[str, object]]:
        return [
            {
                "id": str(item.id),
                "name": item.name,
                "enabled": item.enabled,
                "database_backend": (
                    item.database_backend
                ),
                "schedule": (
                    item.schedule_json or {}
                ),
                "retention": (
                    item.retention_policy_json
                    or {}
                ),
                "verify_after_backup": (
                    item.verify_after_backup
                ),
                "repository_check_schedule": (
                    item.repository_check_schedule_json
                    or {}
                ),
                "include_deployment_config": (
                    item.include_deployment_config
                ),
                "repository_configured": bool(
                    item.repository_config_ref
                ),
                "credentials_configured": (
                    item.credential_secret_ref
                    is not None
                ),
            }
            for item in session.scalars(
                select(BackupPolicy).order_by(
                    BackupPolicy.name,
                    BackupPolicy.id,
                )
            )
        ]

    @classmethod
    def build(
        cls,
        session: Session,
        *,
        settings: Settings,
    ) -> dict[str, Any]:
        return {
            "format": cls.FORMAT,
            "format_version": cls.VERSION,
            "exported_at": datetime.now(
                UTC
            ).isoformat(),
            "application_version": (
                settings.app_version
            ),
            "secrets_included": False,
            "sections": {
                "general": cls._general(
                    session,
                    settings,
                ),
                "time": cls._time_settings(
                    session
                ),
                "roles": cls._roles(
                    session
                ),
                "devices": cls._devices(
                    session
                ),
                "cameras": cls._cameras(
                    session
                ),
                "recording": cls._recording(
                    session
                ),
                "storage_targets": (
                    cls._storage(session)
                ),
                "alert_policies": (
                    cls._alerts(session)
                ),
                "notification_targets": (
                    cls._notifications(session)
                ),
                "oidc_providers": (
                    cls._oidc(session)
                ),
                "frigate": (
                    cls._frigate(session)
                ),
                "backup_policies": (
                    cls._backups(session)
                ),
            },
            "excluded": [
                "secret_records",
                "users",
                "user_sessions",
                "personal_api_tokens",
                "password_reset_tokens",
                "external_identities",
                "audit_events",
                "events",
                "alerts",
                "notification_deliveries",
                "recording_segments",
                "recording_locations",
                "recording_triggers",
                "recording_protections",
                "backup_sets",
                "export_jobs",
                "runtime_cache",
            ],
        }
