from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.alerts.models import AlertPolicy
from app.modules.alerts.service import AlertPolicyService
from app.modules.auth.admin_service import AuthAdminService
from app.modules.auth.camera_scope import CameraScopeService
from app.modules.auth.models import Role
from app.modules.auth.oidc import OidcProviderSettingsService
from app.modules.backups.models import BackupPolicy
from app.modules.backups.service import BackupPolicyService
from app.modules.cameras.groups import CameraGroupService
from app.modules.cameras.models import (
    Camera,
    CameraGroup,
    CameraStreamProfile,
    Device,
    DeviceEndpoint,
)
from app.modules.cameras.service import CameraService
from app.modules.notifications.models import NotificationTarget
from app.modules.notifications.service import NotificationTargetService
from app.modules.recordings.models import RecordingPolicy, RetentionPolicy
from app.modules.recordings.policy import RecordingPolicyService
from app.modules.storage.models import StorageTarget
from app.modules.storage.retention_admin import RetentionPolicyAdminService
from app.modules.storage.service import StorageTargetService

from .settings import SystemSettingsService, TimeSystemSettingsService


_FORBIDDEN_KEYS = frozenset(
    {
        "secret_ref",
        "credential_secret_ref",
        "repository_config_ref",
        "stream_uri_ref",
        "encrypted_payload",
        "token_hash",
        "password_hash",
        "client_secret",
        "rclone_config",
        "rtsp_url",
        "stream_uri",
        "http_bearer_token",
        "http_password",
        "mqtt_password",
        "secret_access_key",
        "access_key_id",
        "password",
    }
)

_KNOWN_SECTIONS = frozenset(
    {
        "general",
        "time",
        "roles",
        "devices",
        "cameras",
        "recording",
        "storage_targets",
        "alert_policies",
        "notification_targets",
        "oidc_providers",
        "frigate",
        "backup_policies",
    }
)


@dataclass(frozen=True, slots=True)
class CredentialRequirement:
    section: str
    resource_type: str
    resource_id: str | None
    name: str | None
    credential: str


@dataclass(frozen=True, slots=True)
class ConfigurationValidation:
    source_application_version: str | None
    section_counts: dict[str, int]
    credentials_required: tuple[
        CredentialRequirement,
        ...,
    ]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfigurationApplyItem:
    section: str
    resource_type: str
    source_id: str | None
    target_id: str | None
    name: str | None
    action: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigurationApplyResult:
    applied: tuple[ConfigurationApplyItem, ...]
    skipped: tuple[ConfigurationApplyItem, ...]
    warnings: tuple[str, ...]
    camera_ids_to_reconcile: tuple[uuid.UUID, ...]


class ConfigurationImportService:
    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        details: dict[str, object]
        | None = None,
    ) -> ApiError:
        return ApiError(
            status_code=400,
            code=code,
            message=message,
            details=details or {},
        )

    @classmethod
    def _reject_secret_fields(
        cls,
        value: object,
        *,
        path: str = "$",
    ) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise cls._error(
                        "configuration_import_invalid",
                        "Configuration object keys must be strings.",
                        details={"path": path},
                    )
                if key.lower() in _FORBIDDEN_KEYS:
                    raise cls._error(
                        "configuration_import_secret_field",
                        "Configuration import contains a secret-bearing field.",
                        details={
                            "path": f"{path}.{key}",
                            "field": key,
                        },
                    )
                cls._reject_secret_fields(
                    child,
                    path=f"{path}.{key}",
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                cls._reject_secret_fields(
                    child,
                    path=f"{path}[{index}]",
                )

    @classmethod
    def _mapping(
        cls,
        value: object,
        *,
        path: str,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise cls._error(
                "configuration_import_invalid",
                "Configuration section must be an object.",
                details={"path": path},
            )
        return value

    @classmethod
    def _items(
        cls,
        value: object,
        *,
        path: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise cls._error(
                "configuration_import_invalid",
                "Configuration section must be a list.",
                details={"path": path},
            )
        result: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise cls._error(
                    "configuration_import_invalid",
                    "Configuration resource must be an object.",
                    details={
                        "path": f"{path}[{index}]"
                    },
                )
            result.append(item)
        return result

    @classmethod
    def _id_set(
        cls,
        items: Iterable[dict[str, Any]],
        *,
        path: str,
    ) -> set[str]:
        result: set[str] = set()
        for index, item in enumerate(items):
            raw = item.get("id")
            if not isinstance(raw, str) or not raw:
                raise cls._error(
                    "configuration_import_invalid",
                    "Configuration resource is missing an id.",
                    details={
                        "path": f"{path}[{index}].id"
                    },
                )
            if raw in result:
                raise cls._error(
                    "configuration_import_duplicate_id",
                    "Configuration contains a duplicate resource id.",
                    details={
                        "path": f"{path}[{index}].id",
                        "id": raw,
                    },
                )
            result.add(raw)
        return result

    @classmethod
    def _require_ref(
        cls,
        value: object,
        allowed: set[str],
        *,
        path: str,
        nullable: bool = False,
    ) -> str | None:
        if value is None and nullable:
            return None
        if (
            not isinstance(value, str)
            or value not in allowed
        ):
            raise cls._error(
                "configuration_import_reference_invalid",
                "Configuration contains a broken resource reference.",
                details={
                    "path": path,
                    "reference": (
                        str(value)
                        if value is not None
                        else None
                    ),
                },
            )
        return value

    @staticmethod
    def _requirement(
        result: list[CredentialRequirement],
        *,
        section: str,
        resource_type: str,
        item: dict[str, Any],
        credential: str,
    ) -> None:
        result.append(
            CredentialRequirement(
                section=section,
                resource_type=resource_type,
                resource_id=(
                    str(item["id"])
                    if item.get("id")
                    is not None
                    else None
                ),
                name=(
                    str(item["name"])
                    if item.get("name")
                    is not None
                    else None
                ),
                credential=credential,
            )
        )

    @classmethod
    def validate(
        cls,
        bundle: dict[str, Any],
        *,
        settings: Settings,
    ) -> ConfigurationValidation:
        if bundle.get("format") != (
            "zero-nvr.configuration"
        ):
            raise cls._error(
                "configuration_import_format_invalid",
                "Configuration import format is not supported.",
            )
        if bundle.get("format_version") != 1:
            raise cls._error(
                "configuration_import_version_unsupported",
                "Configuration import version is not supported.",
                details={
                    "format_version": (
                        bundle.get("format_version")
                    )
                },
            )
        if bundle.get("secrets_included") is not False:
            raise cls._error(
                "configuration_import_secrets_not_allowed",
                "Configuration import must not contain secret material.",
            )

        cls._reject_secret_fields(bundle)

        sections = cls._mapping(
            bundle.get("sections"),
            path="$.sections",
        )
        unknown = set(sections) - _KNOWN_SECTIONS
        if unknown:
            raise cls._error(
                "configuration_import_section_unsupported",
                "Configuration import contains unsupported sections.",
                details={
                    "sections": sorted(
                        str(item)
                        for item in unknown
                    )
                },
            )

        general = cls._mapping(
            sections.get("general", {}),
            path="$.sections.general",
        )
        time_settings = cls._mapping(
            sections.get("time", {}),
            path="$.sections.time",
        )
        if time_settings:
            TimeSystemSettingsService.normalize(
                current=None,
                legacy=None,
                changes=dict(time_settings),
            )
        roles = cls._items(
            sections.get("roles", []),
            path="$.sections.roles",
        )
        devices_section = cls._mapping(
            sections.get("devices", {}),
            path="$.sections.devices",
        )
        devices = cls._items(
            devices_section.get("devices", []),
            path=(
                "$.sections.devices.devices"
            ),
        )
        endpoints = cls._items(
            devices_section.get(
                "endpoints",
                [],
            ),
            path=(
                "$.sections.devices.endpoints"
            ),
        )
        device_credentials = cls._items(
            devices_section.get(
                "credentials",
                [],
            ),
            path=(
                "$.sections.devices.credentials"
            ),
        )

        cameras_section = cls._mapping(
            sections.get("cameras", {}),
            path="$.sections.cameras",
        )
        cameras = cls._items(
            cameras_section.get("cameras", []),
            path=(
                "$.sections.cameras.cameras"
            ),
        )
        profiles = cls._items(
            cameras_section.get(
                "stream_profiles",
                [],
            ),
            path=(
                "$.sections.cameras.stream_profiles"
            ),
        )
        bindings = cls._items(
            cameras_section.get(
                "stream_bindings",
                [],
            ),
            path=(
                "$.sections.cameras.stream_bindings"
            ),
        )
        groups = cls._items(
            cameras_section.get("groups", []),
            path=(
                "$.sections.cameras.groups"
            ),
        )
        members = cls._items(
            cameras_section.get(
                "group_members",
                [],
            ),
            path=(
                "$.sections.cameras.group_members"
            ),
        )

        recording_section = cls._mapping(
            sections.get("recording", {}),
            path="$.sections.recording",
        )
        recording_policies = cls._items(
            recording_section.get(
                "policies",
                [],
            ),
            path=(
                "$.sections.recording.policies"
            ),
        )
        retention_policies = cls._items(
            recording_section.get(
                "retention_policies",
                [],
            ),
            path=(
                "$.sections.recording.retention_policies"
            ),
        )
        storage_targets = cls._items(
            sections.get(
                "storage_targets",
                [],
            ),
            path=(
                "$.sections.storage_targets"
            ),
        )
        alert_policies = cls._items(
            sections.get(
                "alert_policies",
                [],
            ),
            path=(
                "$.sections.alert_policies"
            ),
        )
        notification_targets = cls._items(
            sections.get(
                "notification_targets",
                [],
            ),
            path=(
                "$.sections.notification_targets"
            ),
        )
        oidc_providers = cls._items(
            sections.get(
                "oidc_providers",
                [],
            ),
            path=(
                "$.sections.oidc_providers"
            ),
        )
        frigate = sections.get("frigate")
        if (
            frigate is not None
            and not isinstance(frigate, dict)
        ):
            raise cls._error(
                "configuration_import_invalid",
                "Frigate configuration must be an object or null.",
                details={
                    "path": "$.sections.frigate"
                },
            )
        backup_policies = cls._items(
            sections.get(
                "backup_policies",
                [],
            ),
            path=(
                "$.sections.backup_policies"
            ),
        )

        role_ids = cls._id_set(
            roles,
            path="$.sections.roles",
        )
        device_ids = cls._id_set(
            devices,
            path=(
                "$.sections.devices.devices"
            ),
        )
        device_adapter_types = {
            str(item["id"]): str(
                item.get(
                    "adapter_type",
                    "",
                )
            )
            for item in devices
        }

        endpoint_ids = cls._id_set(
            endpoints,
            path=(
                "$.sections.devices.endpoints"
            ),
        )
        camera_ids = cls._id_set(
            cameras,
            path=(
                "$.sections.cameras.cameras"
            ),
        )
        profile_ids = cls._id_set(
            profiles,
            path=(
                "$.sections.cameras.stream_profiles"
            ),
        )
        group_ids = cls._id_set(
            groups,
            path=(
                "$.sections.cameras.groups"
            ),
        )
        storage_ids = cls._id_set(
            storage_targets,
            path=(
                "$.sections.storage_targets"
            ),
        )
        retention_ids = cls._id_set(
            retention_policies,
            path=(
                "$.sections.recording.retention_policies"
            ),
        )
        notification_ids = cls._id_set(
            notification_targets,
            path=(
                "$.sections.notification_targets"
            ),
        )

        endpoint_devices: dict[str, str] = {}
        for index, item in enumerate(endpoints):
            device_id = cls._require_ref(
                item.get("device_id"),
                device_ids,
                path=(
                    "$.sections.devices.endpoints"
                    f"[{index}].device_id"
                ),
            )
            assert device_id is not None
            endpoint_devices[
                str(item["id"])
            ] = device_id

        for index, item in enumerate(
            device_credentials
        ):
            device_id = cls._require_ref(
                item.get("device_id"),
                device_ids,
                path=(
                    "$.sections.devices.credentials"
                    f"[{index}].device_id"
                ),
            )
            endpoint_id = item.get(
                "endpoint_id"
            )
            if endpoint_id is not None:
                endpoint = cls._require_ref(
                    endpoint_id,
                    endpoint_ids,
                    path=(
                        "$.sections.devices.credentials"
                        f"[{index}].endpoint_id"
                    ),
                )
                assert endpoint is not None
                if (
                    endpoint_devices.get(endpoint)
                    != device_id
                ):
                    raise cls._error(
                        "configuration_import_reference_invalid",
                        "Device credential endpoint belongs to a different device.",
                        details={
                            "path": (
                                "$.sections.devices.credentials"
                                f"[{index}].endpoint_id"
                            )
                        },
                    )

        for index, item in enumerate(cameras):
            maintenance = item.get(
                "maintenance"
            )
            if (
                maintenance is not None
                and not isinstance(
                    maintenance,
                    bool,
                )
            ):
                raise cls._error(
                    "configuration_import_invalid",
                    "Camera maintenance state is invalid.",
                    details={
                        "path": (
                            "$.sections.cameras.cameras"
                            f"[{index}].maintenance"
                        )
                    },
                )
            mode = item.get(
                "time_sync_mode"
            )
            if (
                mode is not None
                and (
                    not isinstance(mode, str)
                    or mode not in {
                        "monitor",
                        "manage_ntp",
                        "ignore",
                    }
                )
            ):
                raise cls._error(
                    "configuration_import_invalid",
                    "Camera time synchronization mode is invalid.",
                    details={
                        "path": (
                            "$.sections.cameras.cameras"
                            f"[{index}].time_sync_mode"
                        )
                    },
                )
            device_id = cls._require_ref(
                item.get("device_id"),
                device_ids,
                path=(
                    "$.sections.cameras.cameras"
                    f"[{index}].device_id"
                ),
                nullable=True,
            )
            if (
                mode is not None
                and mode != "ignore"
                and (
                    device_id is None
                    or device_adapter_types.get(
                        device_id
                    )
                    != "onvif"
                )
            ):
                raise cls._error(
                    "configuration_import_invalid",
                    (
                        "Camera time synchronization mode "
                        "requires an ONVIF device."
                    ),
                    details={
                        "path": (
                            "$.sections.cameras.cameras"
                            f"[{index}].time_sync_mode"
                        )
                    },
                )

        profile_camera: dict[str, str] = {}
        for index, item in enumerate(profiles):
            camera_id = cls._require_ref(
                item.get("camera_id"),
                camera_ids,
                path=(
                    "$.sections.cameras.stream_profiles"
                    f"[{index}].camera_id"
                ),
            )
            assert camera_id is not None
            profile_camera[
                str(item["id"])
            ] = camera_id

        for index, item in enumerate(bindings):
            camera_id = cls._require_ref(
                item.get("camera_id"),
                camera_ids,
                path=(
                    "$.sections.cameras.stream_bindings"
                    f"[{index}].camera_id"
                ),
            )
            profile_id = cls._require_ref(
                item.get("stream_profile_id"),
                profile_ids,
                path=(
                    "$.sections.cameras.stream_bindings"
                    f"[{index}].stream_profile_id"
                ),
            )
            if (
                profile_id is not None
                and camera_id is not None
                and profile_camera.get(profile_id)
                != camera_id
            ):
                raise cls._error(
                    "configuration_import_reference_invalid",
                    "Camera stream binding references a profile from another camera.",
                    details={
                        "path": (
                            "$.sections.cameras.stream_bindings"
                            f"[{index}].stream_profile_id"
                        )
                    },
                )

        for index, item in enumerate(groups):
            parent = item.get("parent_id")
            if parent is None:
                continue
            resolved = cls._require_ref(
                parent,
                group_ids,
                path=(
                    "$.sections.cameras.groups"
                    f"[{index}].parent_id"
                ),
            )
            if resolved == item.get("id"):
                raise cls._error(
                    "configuration_import_reference_invalid",
                    "Camera group cannot be its own parent.",
                    details={
                        "path": (
                            "$.sections.cameras.groups"
                            f"[{index}].parent_id"
                        )
                    },
                )

        for index, item in enumerate(members):
            cls._require_ref(
                item.get("camera_group_id"),
                group_ids,
                path=(
                    "$.sections.cameras.group_members"
                    f"[{index}].camera_group_id"
                ),
            )
            cls._require_ref(
                item.get("camera_id"),
                camera_ids,
                path=(
                    "$.sections.cameras.group_members"
                    f"[{index}].camera_id"
                ),
            )

        for index, item in enumerate(roles):
            scope = item.get("camera_scope")
            if scope is None:
                continue
            scope = cls._mapping(
                scope,
                path=(
                    "$.sections.roles"
                    f"[{index}].camera_scope"
                ),
            )
            for camera_index, camera_id in enumerate(
                scope.get(
                    "camera_ids",
                    [],
                )
            ):
                cls._require_ref(
                    camera_id,
                    camera_ids,
                    path=(
                        "$.sections.roles"
                        f"[{index}].camera_scope.camera_ids"
                        f"[{camera_index}]"
                    ),
                )
            for group_index, group_id in enumerate(
                scope.get(
                    "camera_group_ids",
                    [],
                )
            ):
                cls._require_ref(
                    group_id,
                    group_ids,
                    path=(
                        "$.sections.roles"
                        f"[{index}].camera_scope.camera_group_ids"
                        f"[{group_index}]"
                    ),
                )

        for index, item in enumerate(
            retention_policies
        ):
            scope_type = item.get(
                "scope_type"
            )
            scope_id = item.get("scope_id")
            if scope_type == "GLOBAL":
                if scope_id is not None:
                    raise cls._error(
                        "configuration_import_reference_invalid",
                        "Global retention policy must not have a scope id.",
                        details={
                            "path": (
                                "$.sections.recording.retention_policies"
                                f"[{index}].scope_id"
                            )
                        },
                    )
            elif scope_type == "CAMERA":
                cls._require_ref(
                    scope_id,
                    camera_ids,
                    path=(
                        "$.sections.recording.retention_policies"
                        f"[{index}].scope_id"
                    ),
                )
            elif scope_type == "CAMERA_GROUP":
                cls._require_ref(
                    scope_id,
                    group_ids,
                    path=(
                        "$.sections.recording.retention_policies"
                        f"[{index}].scope_id"
                    ),
                )
            else:
                raise cls._error(
                    "configuration_import_invalid",
                    "Retention policy scope type is invalid.",
                    details={
                        "path": (
                            "$.sections.recording.retention_policies"
                            f"[{index}].scope_type"
                        )
                    },
                )

        for index, item in enumerate(
            recording_policies
        ):
            cls._require_ref(
                item.get("camera_id"),
                camera_ids,
                path=(
                    "$.sections.recording.policies"
                    f"[{index}].camera_id"
                ),
            )
            cls._require_ref(
                item.get("storage_target_id"),
                storage_ids,
                path=(
                    "$.sections.recording.policies"
                    f"[{index}].storage_target_id"
                ),
                nullable=True,
            )
            cls._require_ref(
                item.get(
                    "retention_policy_id"
                ),
                retention_ids,
                path=(
                    "$.sections.recording.policies"
                    f"[{index}].retention_policy_id"
                ),
                nullable=True,
            )

        for index, item in enumerate(
            oidc_providers
        ):
            roles_raw = item.get(
                "default_role_ids",
                [],
            )
            if not isinstance(roles_raw, list):
                raise cls._error(
                    "configuration_import_invalid",
                    "OIDC default role ids must be a list.",
                    details={
                        "path": (
                            "$.sections.oidc_providers"
                            f"[{index}].default_role_ids"
                        )
                    },
                )
            for role_index, role_id in enumerate(
                roles_raw
            ):
                cls._require_ref(
                    role_id,
                    role_ids,
                    path=(
                        "$.sections.oidc_providers"
                        f"[{index}].default_role_ids"
                        f"[{role_index}]"
                    ),
                )

        if isinstance(frigate, dict):
            camera_map = frigate.get(
                "camera_map",
                {},
            )
            if not isinstance(camera_map, dict):
                raise cls._error(
                    "configuration_import_invalid",
                    "Frigate camera map must be an object.",
                    details={
                        "path": (
                            "$.sections.frigate.camera_map"
                        )
                    },
                )
            for key, camera_id in camera_map.items():
                cls._require_ref(
                    camera_id,
                    camera_ids,
                    path=(
                        "$.sections.frigate.camera_map."
                        + str(key)
                    ),
                )

        for index, item in enumerate(
            alert_policies
        ):
            match = item.get("match", {})
            action = item.get("action", {})
            if not isinstance(match, dict):
                raise cls._error(
                    "configuration_import_invalid",
                    "Alert match configuration must be an object.",
                    details={
                        "path": (
                            "$.sections.alert_policies"
                            f"[{index}].match"
                        )
                    },
                )
            if not isinstance(action, dict):
                raise cls._error(
                    "configuration_import_invalid",
                    "Alert action configuration must be an object.",
                    details={
                        "path": (
                            "$.sections.alert_policies"
                            f"[{index}].action"
                        )
                    },
                )
            for camera_index, camera_id in enumerate(
                match.get("camera_ids", [])
            ):
                cls._require_ref(
                    camera_id,
                    camera_ids,
                    path=(
                        "$.sections.alert_policies"
                        f"[{index}].match.camera_ids"
                        f"[{camera_index}]"
                    ),
                )
            for target_index, target_id in enumerate(
                action.get(
                    "notification_target_ids",
                    [],
                )
            ):
                cls._require_ref(
                    target_id,
                    notification_ids,
                    path=(
                        "$.sections.alert_policies"
                        f"[{index}].action.notification_target_ids"
                        f"[{target_index}]"
                    ),
                )

        requirements: list[
            CredentialRequirement
        ] = []
        for item in device_credentials:
            if item.get(
                "credentials_configured"
            ) is True:
                cls._requirement(
                    requirements,
                    section="devices",
                    resource_type="device_credential",
                    item=item,
                    credential=str(
                        item.get("kind")
                        or "device"
                    ),
                )
        for item in profiles:
            if item.get(
                "stream_uri_configured"
            ) is True:
                cls._requirement(
                    requirements,
                    section="cameras",
                    resource_type="camera_stream_profile",
                    item=item,
                    credential="stream_uri",
                )
        for item in storage_targets:
            if item.get(
                "credentials_configured"
            ) is True:
                cls._requirement(
                    requirements,
                    section="storage_targets",
                    resource_type="storage_target",
                    item=item,
                    credential="rclone_config",
                )
        for item in notification_targets:
            if item.get(
                "url_configured"
            ) is True:
                cls._requirement(
                    requirements,
                    section="notification_targets",
                    resource_type="notification_target",
                    item=item,
                    credential="apprise_url",
                )
            if item.get(
                "credentials_configured"
            ) is True:
                cls._requirement(
                    requirements,
                    section="notification_targets",
                    resource_type="notification_target",
                    item=item,
                    credential="smtp_credentials",
                )
        for item in oidc_providers:
            if item.get(
                "client_secret_configured"
            ) is True:
                cls._requirement(
                    requirements,
                    section="oidc_providers",
                    resource_type="oidc_provider",
                    item=item,
                    credential="client_secret",
                )
        if (
            isinstance(frigate, dict)
            and frigate.get(
                "credentials_configured"
            ) is True
        ):
            cls._requirement(
                requirements,
                section="frigate",
                resource_type="frigate_provider",
                item={
                    "id": None,
                    "name": "Frigate",
                },
                credential="integration_credentials",
            )
        for item in backup_policies:
            if item.get(
                "repository_configured"
            ) is True:
                cls._requirement(
                    requirements,
                    section="backup_policies",
                    resource_type="backup_policy",
                    item=item,
                    credential="repository",
                )
            if item.get(
                "credentials_configured"
            ) is True:
                cls._requirement(
                    requirements,
                    section="backup_policies",
                    resource_type="backup_policy",
                    item=item,
                    credential="repository_credentials",
                )

        section_counts = {
            "general": 1 if general else 0,
            "time": 1 if time_settings else 0,
            "roles": len(roles),
            "devices": (
                len(devices)
                + len(endpoints)
                + len(device_credentials)
            ),
            "cameras": (
                len(cameras)
                + len(profiles)
                + len(bindings)
                + len(groups)
                + len(members)
            ),
            "recording": (
                len(recording_policies)
                + len(retention_policies)
            ),
            "storage_targets": (
                len(storage_targets)
            ),
            "alert_policies": (
                len(alert_policies)
            ),
            "notification_targets": (
                len(notification_targets)
            ),
            "oidc_providers": (
                len(oidc_providers)
            ),
            "frigate": (
                1
                if isinstance(frigate, dict)
                else 0
            ),
            "backup_policies": (
                len(backup_policies)
            ),
        }

        source_version = bundle.get(
            "application_version"
        )
        if source_version is not None:
            source_version = str(
                source_version
            )

        warnings = [
            (
                "Users, sessions, API tokens, audit history, "
                "event history, recording catalog and secret "
                "material are intentionally not part of "
                "configuration import."
            )
        ]
        if requirements:
            warnings.append(
                (
                    f"{len(requirements)} credential input(s) "
                    "must be supplied separately after import."
                )
            )
        if (
            source_version
            and source_version
            != settings.app_version
        ):
            warnings.append(
                (
                    "Configuration was exported by zero-nvr "
                    f"{source_version}; this system is "
                    f"{settings.app_version}."
                )
            )

        return ConfigurationValidation(
            source_application_version=(
                source_version
            ),
            section_counts=section_counts,
            credentials_required=tuple(
                requirements
            ),
            warnings=tuple(warnings),
        )


    @staticmethod
    def _source_uuid(
        item: dict[str, Any],
    ) -> uuid.UUID:
        return uuid.UUID(str(item["id"]))

    @staticmethod
    def _apply_item(
        *,
        section: str,
        resource_type: str,
        item: dict[str, Any],
        action: str,
        target_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> ConfigurationApplyItem:
        source_id = item.get("id")
        name = item.get("name")
        return ConfigurationApplyItem(
            section=section,
            resource_type=resource_type,
            source_id=(
                str(source_id)
                if source_id is not None
                else None
            ),
            target_id=(
                str(target_id)
                if target_id is not None
                else None
            ),
            name=(
                str(name)
                if name is not None
                else None
            ),
            action=action,
            reason=reason,
        )

    @staticmethod
    def _existing_by_name(
        session: Session,
        model,
        name: str,
    ):
        return session.scalar(
            select(model).where(
                model.name == name
            )
        )

    @classmethod
    def apply(
        cls,
        session: Session,
        *,
        settings: Settings,
        bundle: dict[str, Any],
    ) -> ConfigurationApplyResult:
        validation = cls.validate(
            bundle,
            settings=settings,
        )
        sections = bundle["sections"]
        assert isinstance(sections, dict)

        applied: list[
            ConfigurationApplyItem
        ] = []
        skipped: list[
            ConfigurationApplyItem
        ] = []
        reconcile: set[uuid.UUID] = set()

        role_map: dict[str, uuid.UUID] = {}
        device_map: dict[str, uuid.UUID] = {}
        camera_map: dict[str, uuid.UUID] = {}
        profile_map: dict[str, uuid.UUID] = {}
        group_map: dict[str, uuid.UUID] = {}
        storage_map: dict[str, uuid.UUID] = {}
        retention_map: dict[str, uuid.UUID] = {}
        notification_map: dict[
            str,
            uuid.UUID,
        ] = {}

        general = sections.get(
            "general",
            {},
        )
        time_changes: dict[str, object] = {}
        if isinstance(general, dict) and general:
            general_changes = dict(general)
            legacy_timezone = general_changes.pop(
                "display_timezone",
                None,
            )
            legacy_servers = general_changes.pop(
                "camera_ntp_servers",
                None,
            )
            if general_changes:
                SystemSettingsService.update(
                    session,
                    settings=settings,
                    changes=general_changes,
                )
            if legacy_timezone is not None:
                time_changes[
                    "recording_timezone"
                ] = legacy_timezone
            if legacy_servers is not None:
                time_changes[
                    "managed_camera_ntp_servers"
                ] = legacy_servers
                time_changes[
                    "managed_camera_ntp_mode"
                ] = (
                    "manual"
                    if legacy_servers
                    else "dhcp"
                )
            applied.append(
                ConfigurationApplyItem(
                    section="general",
                    resource_type="system_settings",
                    source_id=None,
                    target_id=None,
                    name="General",
                    action="updated",
                )
            )

        time_section = sections.get(
            "time",
            {},
        )
        if isinstance(time_section, dict):
            time_changes.update(
                dict(time_section)
            )
        if time_changes:
            TimeSystemSettingsService.update(
                session,
                changes=time_changes,
            )
            applied.append(
                ConfigurationApplyItem(
                    section="time",
                    resource_type="system_settings",
                    source_id=None,
                    target_id=None,
                    name="Time",
                    action="updated",
                )
            )

        roles = sections.get("roles", [])
        assert isinstance(roles, list)
        for raw in roles:
            assert isinstance(raw, dict)
            item = raw
            source_id = str(item["id"])
            name = str(item["name"])
            source_builtin = bool(
                item.get("built_in", False)
            )
            target = cls._existing_by_name(
                session,
                Role,
                name,
            )

            if source_builtin:
                if (
                    target is None
                    or not target.built_in
                ):
                    skipped.append(
                        cls._apply_item(
                            section="roles",
                            resource_type="role",
                            item=item,
                            action="skipped",
                            reason=(
                                "builtin_role_unavailable"
                            ),
                        )
                    )
                    continue
                role_map[source_id] = target.id
                applied.append(
                    cls._apply_item(
                        section="roles",
                        resource_type="role",
                        item=item,
                        action="matched",
                        target_id=target.id,
                    )
                )
                continue

            permissions = item.get(
                "permissions",
                [],
            )
            if not isinstance(
                permissions,
                list,
            ):
                raise cls._error(
                    "configuration_import_invalid",
                    "Role permissions must be a list.",
                )
            description = item.get(
                "description"
            )
            description_text = (
                str(description)
                if description is not None
                else None
            )

            if target is None:
                target = (
                    AuthAdminService.create_role(
                        session,
                        name=name,
                        description=(
                            description_text
                        ),
                        permissions=[
                            str(value)
                            for value in permissions
                        ],
                    )
                )
                action = "created"
            elif target.built_in:
                skipped.append(
                    cls._apply_item(
                        section="roles",
                        resource_type="role",
                        item=item,
                        action="skipped",
                        target_id=target.id,
                        reason="role_name_conflict",
                    )
                )
                continue
            else:
                target = (
                    AuthAdminService.update_role(
                        session,
                        role=target,
                        changes={
                            "description": (
                                description_text
                            ),
                            "permissions": [
                                str(value)
                                for value
                                in permissions
                            ],
                        },
                    )
                )
                action = "updated"

            role_map[source_id] = target.id
            applied.append(
                cls._apply_item(
                    section="roles",
                    resource_type="role",
                    item=item,
                    action=action,
                    target_id=target.id,
                )
            )

        devices_section = sections.get(
            "devices",
            {},
        )
        assert isinstance(
            devices_section,
            dict,
        )
        devices = devices_section.get(
            "devices",
            [],
        )
        endpoints = devices_section.get(
            "endpoints",
            [],
        )
        credentials = devices_section.get(
            "credentials",
            [],
        )
        assert isinstance(devices, list)
        assert isinstance(endpoints, list)
        assert isinstance(credentials, list)

        source_endpoints: dict[
            str,
            list[dict[str, Any]],
        ] = defaultdict(list)
        for raw in endpoints:
            assert isinstance(raw, dict)
            source_endpoints[
                str(raw["device_id"])
            ].append(raw)

        for raw in devices:
            assert isinstance(raw, dict)
            item = raw
            source_uuid = cls._source_uuid(
                item
            )
            source_id = str(source_uuid)
            target = session.get(
                Device,
                source_uuid,
            )

            if target is None:
                hardware_id = item.get(
                    "hardware_id"
                )
                if (
                    isinstance(hardware_id, str)
                    and hardware_id
                ):
                    matches = list(
                        session.scalars(
                            select(Device).where(
                                Device.hardware_id
                                == hardware_id
                            )
                        )
                    )
                    if len(matches) == 1:
                        target = matches[0]

            if (
                target is None
                and item.get("adapter_type")
                == "manual_rtsp"
            ):
                candidates: set[
                    uuid.UUID
                ] = set()
                for endpoint in (
                    source_endpoints.get(
                        source_id,
                        [],
                    )
                ):
                    host = endpoint.get("host")
                    endpoint_type = (
                        endpoint.get("type")
                    )
                    port = endpoint.get("port")
                    if (
                        not isinstance(host, str)
                        or not isinstance(
                            endpoint_type,
                            str,
                        )
                    ):
                        continue
                    statement = (
                        select(DeviceEndpoint)
                        .where(
                            DeviceEndpoint.type
                            == endpoint_type,
                            DeviceEndpoint.host
                            == host,
                        )
                    )
                    if port is None:
                        statement = (
                            statement.where(
                                DeviceEndpoint.port
                                .is_(None)
                            )
                        )
                    else:
                        statement = (
                            statement.where(
                                DeviceEndpoint.port
                                == port
                            )
                        )
                    for found in (
                        session.scalars(
                            statement
                        )
                    ):
                        device = session.get(
                            Device,
                            found.device_id,
                        )
                        if (
                            device is not None
                            and device.adapter_type
                            == "manual_rtsp"
                        ):
                            candidates.add(
                                device.id
                            )
                if len(candidates) == 1:
                    target = session.get(
                        Device,
                        next(
                            iter(candidates)
                        ),
                    )

            if target is None:
                skipped.append(
                    cls._apply_item(
                        section="devices",
                        resource_type="device",
                        item=item,
                        action="skipped",
                        reason=(
                            "credentials_required"
                        ),
                    )
                )
                continue

            if (
                str(item.get("adapter_type"))
                != target.adapter_type
            ):
                skipped.append(
                    cls._apply_item(
                        section="devices",
                        resource_type="device",
                        item=item,
                        action="skipped",
                        target_id=target.id,
                        reason=(
                            "adapter_type_mismatch"
                        ),
                    )
                )
                continue

            target.name = str(
                item["name"]
            )
            for field in (
                "manufacturer",
                "model",
                "serial_number",
                "hardware_id",
            ):
                value = item.get(field)
                setattr(
                    target,
                    field,
                    (
                        str(value)
                        if value is not None
                        else None
                    ),
                )
            target.capabilities_json = dict(
                item.get("capabilities")
                or {}
            )
            session.flush()
            device_map[source_id] = target.id
            applied.append(
                cls._apply_item(
                    section="devices",
                    resource_type="device",
                    item=item,
                    action="updated",
                    target_id=target.id,
                )
            )

        for raw in endpoints:
            assert isinstance(raw, dict)
            item = raw
            skipped.append(
                cls._apply_item(
                    section="devices",
                    resource_type="device_endpoint",
                    item=item,
                    action="skipped",
                    reason=(
                        "endpoint_address_preserved"
                    ),
                )
            )
        for raw in credentials:
            assert isinstance(raw, dict)
            item = raw
            skipped.append(
                cls._apply_item(
                    section="devices",
                    resource_type="device_credential",
                    item=item,
                    action="skipped",
                    reason="credential_required",
                )
            )

        cameras_section = sections.get(
            "cameras",
            {},
        )
        assert isinstance(
            cameras_section,
            dict,
        )
        cameras = cameras_section.get(
            "cameras",
            [],
        )
        profiles = cameras_section.get(
            "stream_profiles",
            [],
        )
        bindings = cameras_section.get(
            "stream_bindings",
            [],
        )
        groups = cameras_section.get(
            "groups",
            [],
        )
        members = cameras_section.get(
            "group_members",
            [],
        )
        assert isinstance(cameras, list)
        assert isinstance(profiles, list)
        assert isinstance(bindings, list)
        assert isinstance(groups, list)
        assert isinstance(members, list)

        for raw in cameras:
            assert isinstance(raw, dict)
            item = raw
            source_uuid = cls._source_uuid(
                item
            )
            source_id = str(source_uuid)
            target = session.get(
                Camera,
                source_uuid,
            )
            if target is None:
                source_device = item.get(
                    "device_id"
                )
                target_device = (
                    device_map.get(
                        str(source_device)
                    )
                    if source_device
                    is not None
                    else None
                )
                if target_device is not None:
                    target = session.scalar(
                        select(Camera).where(
                            Camera.device_id
                            == target_device,
                            Camera.channel_key
                            == str(
                                item[
                                    "channel_key"
                                ]
                            ),
                        )
                    )

            if target is None:
                skipped.append(
                    cls._apply_item(
                        section="cameras",
                        resource_type="camera",
                        item=item,
                        action="skipped",
                        reason=(
                            "camera_onboarding_required"
                        ),
                    )
                )
                continue

            before_camera = (
                target.name,
                target.location,
                target.storage_label,
                target.maintenance,
                target.time_sync_mode,
                target.enabled,
            )
            enabled_changed = (
                "enabled" in item
                and bool(
                    item["enabled"]
                )
                != target.enabled
            )
            camera_changes: dict[
                str,
                object,
            ] = {
                "name": str(
                    item["name"]
                ),
                "location": (
                    str(item["location"])
                    if item.get(
                        "location"
                    )
                    is not None
                    else None
                ),
                "storage_label": (
                    str(
                        item["storage_label"]
                    )
                    if item.get(
                        "storage_label"
                    )
                    is not None
                    else None
                ),
            }
            if "maintenance" in item:
                camera_changes[
                    "maintenance"
                ] = bool(
                    item["maintenance"]
                )
            if (
                "time_sync_mode"
                in item
            ):
                camera_changes[
                    "time_sync_mode"
                ] = item[
                    "time_sync_mode"
                ]
            CameraService.update_camera(
                session,
                camera=target,
                changes=camera_changes,
            )
            if "enabled" in item:
                CameraService.set_enabled(
                    session,
                    camera=target,
                    enabled=bool(
                        item["enabled"]
                    ),
                )
            after_camera = (
                target.name,
                target.location,
                target.storage_label,
                target.maintenance,
                target.time_sync_mode,
                target.enabled,
            )
            camera_map[source_id] = target.id
            if before_camera == after_camera:
                applied.append(
                    cls._apply_item(
                        section="cameras",
                        resource_type="camera",
                        item=item,
                        action="matched",
                        target_id=target.id,
                    )
                )
            else:
                applied.append(
                    cls._apply_item(
                        section="cameras",
                        resource_type="camera",
                        item=item,
                        action="updated",
                        target_id=target.id,
                    )
                )
            if enabled_changed:
                reconcile.add(
                    target.id
                )

        for raw in profiles:
            assert isinstance(raw, dict)
            item = raw
            source_uuid = cls._source_uuid(
                item
            )
            source_camera = str(
                item["camera_id"]
            )
            target_camera = camera_map.get(
                source_camera
            )
            if target_camera is None:
                skipped.append(
                    cls._apply_item(
                        section="cameras",
                        resource_type=(
                            "camera_stream_profile"
                        ),
                        item=item,
                        action="skipped",
                        reason=(
                            "camera_onboarding_required"
                        ),
                    )
                )
                continue

            target = session.get(
                CameraStreamProfile,
                source_uuid,
            )
            if target is None:
                target = session.scalar(
                    select(
                        CameraStreamProfile
                    ).where(
                        CameraStreamProfile.camera_id
                        == target_camera,
                        CameraStreamProfile.adapter_profile_key
                        == str(
                            item[
                                "adapter_profile_key"
                            ]
                        ),
                    )
                )
            if (
                target is None
                or target.stream_uri_ref
                is None
            ):
                skipped.append(
                    cls._apply_item(
                        section="cameras",
                        resource_type=(
                            "camera_stream_profile"
                        ),
                        item=item,
                        action="skipped",
                        reason="credential_required",
                    )
                )
                continue
            profile_map[
                str(source_uuid)
            ] = target.id
            applied.append(
                cls._apply_item(
                    section="cameras",
                    resource_type=(
                        "camera_stream_profile"
                    ),
                    item=item,
                    action="matched",
                    target_id=target.id,
                )
            )

        bindings_by_camera: dict[
            str,
            list[dict[str, Any]],
        ] = defaultdict(list)
        for raw in bindings:
            assert isinstance(raw, dict)
            bindings_by_camera[
                str(raw["camera_id"])
            ].append(raw)

        for source_camera, items in (
            bindings_by_camera.items()
        ):
            target_camera = camera_map.get(
                source_camera
            )
            if target_camera is None:
                for item in items:
                    skipped.append(
                        cls._apply_item(
                            section="cameras",
                            resource_type=(
                                "camera_stream_binding"
                            ),
                            item=item,
                            action="skipped",
                            reason=(
                                "camera_onboarding_required"
                            ),
                        )
                    )
                continue

            mapped_bindings: list[
                tuple[str, uuid.UUID, str]
            ] = []
            missing = False
            for item in items:
                target_profile = (
                    profile_map.get(
                        str(
                            item[
                                "stream_profile_id"
                            ]
                        )
                    )
                )
                if target_profile is None:
                    missing = True
                    break
                mapped_bindings.append(
                    (
                        str(item["purpose"]),
                        target_profile,
                        str(
                            item[
                                "selection_mode"
                            ]
                        ),
                    )
                )
            if missing:
                for item in items:
                    skipped.append(
                        cls._apply_item(
                            section="cameras",
                            resource_type=(
                                "camera_stream_binding"
                            ),
                            item=item,
                            action="skipped",
                            reason=(
                                "stream_profile_unmapped"
                            ),
                        )
                    )
                continue

            camera = session.get(
                Camera,
                target_camera,
            )
            assert camera is not None
            before_revision = (
                camera.config_revision
            )
            CameraService(
                settings
            ).replace_bindings(
                session,
                camera=camera,
                bindings=mapped_bindings,
            )
            bindings_changed = (
                camera.config_revision
                != before_revision
            )
            if bindings_changed:
                reconcile.add(
                    target_camera
                )
            for item in items:
                applied.append(
                    cls._apply_item(
                        section="cameras",
                        resource_type=(
                            "camera_stream_binding"
                        ),
                        item=item,
                        action=(
                            "updated"
                            if bindings_changed
                            else "matched"
                        ),
                        target_id=target_camera,
                    )
                )

        member_map: dict[
            str,
            list[str],
        ] = defaultdict(list)
        for raw in members:
            assert isinstance(raw, dict)
            member_map[
                str(
                    raw["camera_group_id"]
                )
            ].append(
                str(raw["camera_id"])
            )

        pending_groups = [
            raw
            for raw in groups
            if isinstance(raw, dict)
        ]
        progress = True
        while pending_groups and progress:
            progress = False
            remaining: list[
                dict[str, Any]
            ] = []
            for item in pending_groups:
                source_id = str(
                    item["id"]
                )
                source_parent = item.get(
                    "parent_id"
                )
                target_parent = None
                if source_parent is not None:
                    target_parent = (
                        group_map.get(
                            str(
                                source_parent
                            )
                        )
                    )
                    if target_parent is None:
                        remaining.append(
                            item
                        )
                        continue

                target_cameras: list[
                    uuid.UUID
                ] = []
                member_missing = False
                for source_camera in (
                    member_map.get(
                        source_id,
                        [],
                    )
                ):
                    target_camera = (
                        camera_map.get(
                            source_camera
                        )
                    )
                    if target_camera is None:
                        member_missing = True
                        break
                    target_cameras.append(
                        target_camera
                    )
                if member_missing:
                    remaining.append(item)
                    continue

                source_uuid = cls._source_uuid(
                    item
                )
                target = session.get(
                    CameraGroup,
                    source_uuid,
                )
                if target is None:
                    target = (
                        cls._existing_by_name(
                            session,
                            CameraGroup,
                            str(item["name"]),
                        )
                    )
                description = item.get(
                    "description"
                )
                if target is None:
                    target = (
                        CameraGroupService.create(
                            session,
                            name=str(
                                item["name"]
                            ),
                            description=(
                                str(description)
                                if description
                                is not None
                                else None
                            ),
                            parent_id=(
                                target_parent
                            ),
                            camera_ids=(
                                target_cameras
                            ),
                        )
                    )
                    action = "created"
                else:
                    target = (
                        CameraGroupService.update(
                            session,
                            group=target,
                            changes={
                                "name": str(
                                    item["name"]
                                ),
                                "description": (
                                    str(description)
                                    if description
                                    is not None
                                    else None
                                ),
                                "parent_id": (
                                    target_parent
                                ),
                                "camera_ids": (
                                    target_cameras
                                ),
                            },
                        )
                    )
                    action = "updated"
                group_map[
                    source_id
                ] = target.id
                applied.append(
                    cls._apply_item(
                        section="cameras",
                        resource_type=(
                            "camera_group"
                        ),
                        item=item,
                        action=action,
                        target_id=target.id,
                    )
                )
                progress = True
            pending_groups = remaining

        for item in pending_groups:
            skipped.append(
                cls._apply_item(
                    section="cameras",
                    resource_type=(
                        "camera_group"
                    ),
                    item=item,
                    action="skipped",
                    reason=(
                        "camera_or_parent_unmapped"
                    ),
                )
            )

        for raw in roles:
            assert isinstance(raw, dict)
            item = raw
            target_role = role_map.get(
                str(item["id"])
            )
            scope = item.get(
                "camera_scope"
            )
            if (
                target_role is None
                or scope is None
            ):
                continue
            assert isinstance(scope, dict)
            mode = str(scope["mode"])
            target_cameras: list[
                uuid.UUID
            ] = []
            target_groups: list[
                uuid.UUID
            ] = []
            missing = False
            for source_id in scope.get(
                "camera_ids",
                [],
            ):
                mapped = camera_map.get(
                    str(source_id)
                )
                if mapped is None:
                    missing = True
                    break
                target_cameras.append(mapped)
            if not missing:
                for source_id in scope.get(
                    "camera_group_ids",
                    [],
                ):
                    mapped = group_map.get(
                        str(source_id)
                    )
                    if mapped is None:
                        missing = True
                        break
                    target_groups.append(mapped)
            if missing:
                skipped.append(
                    cls._apply_item(
                        section="roles",
                        resource_type=(
                            "role_camera_scope"
                        ),
                        item=item,
                        action="skipped",
                        target_id=target_role,
                        reason=(
                            "camera_scope_dependency_unmapped"
                        ),
                    )
                )
                continue
            CameraScopeService.set_scope(
                session,
                principal_type="role",
                principal_id=target_role,
                mode=mode,
                camera_ids=target_cameras,
                camera_group_ids=(
                    target_groups
                ),
            )
            applied.append(
                cls._apply_item(
                    section="roles",
                    resource_type=(
                        "role_camera_scope"
                    ),
                    item=item,
                    action="updated",
                    target_id=target_role,
                )
            )

        storage_service = (
            StorageTargetService(settings)
        )
        storage_targets = sections.get(
            "storage_targets",
            [],
        )
        assert isinstance(
            storage_targets,
            list,
        )
        for raw in storage_targets:
            assert isinstance(raw, dict)
            item = raw
            source_uuid = cls._source_uuid(
                item
            )
            target = session.get(
                StorageTarget,
                source_uuid,
            )
            if target is None:
                target = cls._existing_by_name(
                    session,
                    StorageTarget,
                    str(item["name"]),
                )

            source_type = str(
                item["type"]
            )
            source_role = str(
                item["role"]
            )
            config = dict(
                item.get("config")
                or {}
            )
            if target is not None and (
                target.type != source_type
                or target.role != source_role
            ):
                skipped.append(
                    cls._apply_item(
                        section="storage_targets",
                        resource_type=(
                            "storage_target"
                        ),
                        item=item,
                        action="skipped",
                        target_id=target.id,
                        reason=(
                            "storage_target_type_conflict"
                        ),
                    )
                )
                continue

            if source_type == "rclone":
                if (
                    target is None
                    or target.credential_secret_ref
                    is None
                ):
                    skipped.append(
                        cls._apply_item(
                            section="storage_targets",
                            resource_type=(
                                "storage_target"
                            ),
                            item=item,
                            action="skipped",
                            target_id=(
                                target.id
                                if target
                                is not None
                                else None
                            ),
                            reason=(
                                "credential_required"
                            ),
                        )
                    )
                    continue
                target = storage_service.update(
                    session,
                    target=target,
                    changes={
                        "enabled": bool(
                            item["enabled"]
                        ),
                        "config": config,
                    },
                )
                action = "updated"
            elif target is None:
                target = storage_service.create(
                    session,
                    target_type=source_type,
                    role=source_role,
                    name=str(item["name"]),
                    enabled=bool(
                        item["enabled"]
                    ),
                    config=config,
                    rclone_config=None,
                )
                action = "created"
            else:
                target = storage_service.update(
                    session,
                    target=target,
                    changes={
                        "enabled": bool(
                            item["enabled"]
                        ),
                        "config": config,
                    },
                )
                action = "updated"

            storage_map[
                str(source_uuid)
            ] = target.id
            applied.append(
                cls._apply_item(
                    section="storage_targets",
                    resource_type=(
                        "storage_target"
                    ),
                    item=item,
                    action=action,
                    target_id=target.id,
                )
            )

        retention = (
            sections.get(
                "recording",
                {},
            )
        )
        assert isinstance(retention, dict)
        retention_items = retention.get(
            "retention_policies",
            [],
        )
        assert isinstance(
            retention_items,
            list,
        )
        for raw in retention_items:
            assert isinstance(raw, dict)
            item = raw
            source_uuid = cls._source_uuid(
                item
            )
            scope_type = str(
                item["scope_type"]
            )
            source_scope = item.get(
                "scope_id"
            )
            target_scope: uuid.UUID | None = None
            if scope_type == "CAMERA":
                target_scope = (
                    camera_map.get(
                        str(source_scope)
                    )
                )
            elif (
                scope_type
                == "CAMERA_GROUP"
            ):
                target_scope = (
                    group_map.get(
                        str(source_scope)
                    )
                )
            if (
                scope_type != "GLOBAL"
                and target_scope is None
            ):
                skipped.append(
                    cls._apply_item(
                        section="recording",
                        resource_type=(
                            "retention_policy"
                        ),
                        item=item,
                        action="skipped",
                        reason=(
                            "scope_dependency_unmapped"
                        ),
                    )
                )
                continue

            target = session.get(
                RetentionPolicy,
                source_uuid,
            )
            if target is None:
                target = (
                    cls._existing_by_name(
                        session,
                        RetentionPolicy,
                        str(item["name"]),
                    )
                )
            if target is None:
                statement = select(
                    RetentionPolicy
                ).where(
                    RetentionPolicy.scope_type
                    == scope_type
                )
                if target_scope is None:
                    statement = (
                        statement.where(
                            RetentionPolicy.scope_id
                            .is_(None)
                        )
                    )
                else:
                    statement = (
                        statement.where(
                            RetentionPolicy.scope_id
                            == target_scope
                        )
                    )
                target = session.scalar(
                    statement
                )

            values = {
                "name": str(
                    item["name"]
                ),
                "scope_type": scope_type,
                "scope_id": target_scope,
                "ordinary_keep_days": int(
                    item[
                        "ordinary_keep_days"
                    ]
                ),
                "event_keep_days": int(
                    item["event_keep_days"]
                ),
                "manual_keep_days": int(
                    item["manual_keep_days"]
                ),
                "mode": str(item["mode"]),
                "require_archive_before_delete": bool(
                    item[
                        "require_archive_before_delete"
                    ]
                ),
                "enabled": bool(
                    item["enabled"]
                ),
            }
            if target is None:
                target = (
                    RetentionPolicyAdminService.create(
                        session,
                        **values,
                    )
                )
                action = "created"
            else:
                target = (
                    RetentionPolicyAdminService.update(
                        session,
                        policy=target,
                        changes=values,
                    )
                )
                action = "updated"

            retention_map[
                str(source_uuid)
            ] = target.id
            applied.append(
                cls._apply_item(
                    section="recording",
                    resource_type=(
                        "retention_policy"
                    ),
                    item=item,
                    action=action,
                    target_id=target.id,
                )
            )

        recording_policies = (
            retention.get(
                "policies",
                [],
            )
        )
        assert isinstance(
            recording_policies,
            list,
        )
        for raw in recording_policies:
            assert isinstance(raw, dict)
            item = raw
            target_camera = camera_map.get(
                str(item["camera_id"])
            )
            if target_camera is None:
                skipped.append(
                    cls._apply_item(
                        section="recording",
                        resource_type=(
                            "recording_policy"
                        ),
                        item=item,
                        action="skipped",
                        reason=(
                            "camera_unmapped"
                        ),
                    )
                )
                continue

            source_storage = item.get(
                "storage_target_id"
            )
            target_storage = (
                storage_map.get(
                    str(source_storage)
                )
                if source_storage
                is not None
                else None
            )
            if (
                source_storage is not None
                and target_storage is None
            ):
                skipped.append(
                    cls._apply_item(
                        section="recording",
                        resource_type=(
                            "recording_policy"
                        ),
                        item=item,
                        action="skipped",
                        reason=(
                            "storage_target_unmapped"
                        ),
                    )
                )
                continue

            source_retention = item.get(
                "retention_policy_id"
            )
            target_retention = (
                retention_map.get(
                    str(source_retention)
                )
                if source_retention
                is not None
                else None
            )
            if (
                source_retention
                is not None
                and target_retention
                is None
            ):
                skipped.append(
                    cls._apply_item(
                        section="recording",
                        resource_type=(
                            "recording_policy"
                        ),
                        item=item,
                        action="skipped",
                        reason=(
                            "retention_policy_unmapped"
                        ),
                    )
                )
                continue

            policy_values = {
                "baseline_mode": str(
                    item[
                        "baseline_mode"
                    ]
                ),
                "schedule_json": dict(
                    item.get(
                        "schedule"
                    )
                    or {}
                ),
                "schedule_timezone": (
                    item.get(
                        "schedule_timezone"
                    )
                ),
                "event_recording_enabled": bool(
                    item[
                        "event_recording_enabled"
                    ]
                ),
                "event_filter_json": dict(
                    item.get(
                        "event_filter"
                    )
                    or {}
                ),
                "segment_target_seconds": int(
                    item[
                        "segment_target_seconds"
                    ]
                ),
                "pre_roll_seconds": int(
                    item[
                        "pre_roll_seconds"
                    ]
                ),
                "post_roll_seconds": int(
                    item[
                        "post_roll_seconds"
                    ]
                ),
                "storage_target_id": (
                    target_storage
                ),
                "retention_policy_id": (
                    target_retention
                ),
                "enabled": bool(
                    item["enabled"]
                ),
            }
            existing_policy = session.scalar(
                select(
                    RecordingPolicy
                ).where(
                    RecordingPolicy.camera_id
                    == target_camera
                )
            )
            policy_changed = (
                existing_policy is None
                or any(
                    getattr(
                        existing_policy,
                        key,
                    )
                    != value
                    for key, value
                    in policy_values.items()
                )
            )
            RecordingPolicyService.put(
                session,
                camera_id=target_camera,
                values=policy_values,
            )
            if policy_changed:
                reconcile.add(
                    target_camera
                )
            applied.append(
                cls._apply_item(
                    section="recording",
                    resource_type=(
                        "recording_policy"
                    ),
                    item=item,
                    action=(
                        "updated"
                        if policy_changed
                        else "matched"
                    ),
                    target_id=target_camera,
                )
            )

        notification_service = (
            NotificationTargetService(
                settings
            )
        )
        notification_items = (
            sections.get(
                "notification_targets",
                [],
            )
        )
        assert isinstance(
            notification_items,
            list,
        )
        for raw in notification_items:
            assert isinstance(raw, dict)
            item = raw
            source_uuid = cls._source_uuid(
                item
            )
            target = session.get(
                NotificationTarget,
                source_uuid,
            )
            if target is None:
                target = (
                    cls._existing_by_name(
                        session,
                        NotificationTarget,
                        str(item["name"]),
                    )
                )
            credential_required = bool(
                item.get("url_configured")
                or item.get(
                    "credentials_configured"
                )
            )
            if (
                target is None
                or (
                    credential_required
                    and target.secret_ref is None
                )
            ):
                skipped.append(
                    cls._apply_item(
                        section=(
                            "notification_targets"
                        ),
                        resource_type=(
                            "notification_target"
                        ),
                        item=item,
                        action="skipped",
                        target_id=(
                            target.id
                            if target is not None
                            else None
                        ),
                        reason=(
                            "credential_required"
                        ),
                    )
                )
                continue

            changes = {
                "enabled": bool(
                    item["enabled"]
                ),
                "config": dict(
                    item.get(
                        "config"
                    )
                    or {}
                ),
            }
            if target.kind == "smtp":
                target = (
                    notification_service.update_smtp(
                        session,
                        target=target,
                        changes=changes,
                    )
                )
            else:
                target = (
                    notification_service.update(
                        session,
                        target=target,
                        changes=changes,
                    )
                )
            notification_map[
                str(source_uuid)
            ] = target.id
            applied.append(
                cls._apply_item(
                    section=(
                        "notification_targets"
                    ),
                    resource_type=(
                        "notification_target"
                    ),
                    item=item,
                    action="updated",
                    target_id=target.id,
                )
            )

        oidc_items = sections.get(
            "oidc_providers",
            [],
        )
        assert isinstance(oidc_items, list)
        oidc_service = (
            OidcProviderSettingsService(
                settings
            )
        )
        existing_oidc = {
            item.key: item
            for item in oidc_service.list(
                session
            )
        }
        for raw in oidc_items:
            assert isinstance(raw, dict)
            item = raw
            provider = existing_oidc.get(
                str(item["key"])
            )
            if (
                provider is None
                or provider.secret_ref is None
            ):
                skipped.append(
                    cls._apply_item(
                        section="oidc_providers",
                        resource_type=(
                            "oidc_provider"
                        ),
                        item=item,
                        action="skipped",
                        target_id=(
                            provider.id
                            if provider
                            is not None
                            else None
                        ),
                        reason=(
                            "credential_required"
                        ),
                    )
                )
                continue
            mapped_roles: list[
                uuid.UUID
            ] = []
            role_missing = False
            for source_role in (
                item.get(
                    "default_role_ids",
                    [],
                )
            ):
                target_role = role_map.get(
                    str(source_role)
                )
                if target_role is None:
                    role_missing = True
                    break
                mapped_roles.append(
                    target_role
                )
            if role_missing:
                skipped.append(
                    cls._apply_item(
                        section="oidc_providers",
                        resource_type=(
                            "oidc_provider"
                        ),
                        item=item,
                        action="skipped",
                        target_id=provider.id,
                        reason=(
                            "default_role_unmapped"
                        ),
                    )
                )
                continue
            provider = oidc_service.update(
                session,
                provider=provider,
                changes={
                    "name": str(
                        item["name"]
                    ),
                    "enabled": bool(
                        item["enabled"]
                    ),
                    "issuer": str(
                        item["issuer"]
                    ),
                    "client_id": str(
                        item["client_id"]
                    ),
                    "auto_provision": bool(
                        item[
                            "auto_provision"
                        ]
                    ),
                    "email_linking": bool(
                        item[
                            "email_linking"
                        ]
                    ),
                    "default_role_ids": (
                        mapped_roles
                    ),
                },
            )
            applied.append(
                cls._apply_item(
                    section="oidc_providers",
                    resource_type=(
                        "oidc_provider"
                    ),
                    item=item,
                    action="updated",
                    target_id=provider.id,
                )
            )

        backup_items = sections.get(
            "backup_policies",
            [],
        )
        assert isinstance(backup_items, list)
        backup_service = (
            BackupPolicyService(settings)
        )
        for raw in backup_items:
            assert isinstance(raw, dict)
            item = raw
            source_uuid = cls._source_uuid(
                item
            )
            target = session.get(
                BackupPolicy,
                source_uuid,
            )
            if target is None:
                target = (
                    cls._existing_by_name(
                        session,
                        BackupPolicy,
                        str(item["name"]),
                    )
                )
            if target is None:
                skipped.append(
                    cls._apply_item(
                        section="backup_policies",
                        resource_type=(
                            "backup_policy"
                        ),
                        item=item,
                        action="skipped",
                        reason=(
                            "credential_required"
                        ),
                    )
                )
                continue
            if (
                target.database_backend
                != str(
                    item[
                        "database_backend"
                    ]
                )
            ):
                skipped.append(
                    cls._apply_item(
                        section="backup_policies",
                        resource_type=(
                            "backup_policy"
                        ),
                        item=item,
                        action="skipped",
                        target_id=target.id,
                        reason=(
                            "database_backend_mismatch"
                        ),
                    )
                )
                continue
            target = backup_service.update(
                session,
                policy=target,
                changes={
                    "enabled": bool(
                        item["enabled"]
                    ),
                    "schedule": dict(
                        item.get(
                            "schedule"
                        )
                        or {}
                    ),
                    "retention": dict(
                        item.get(
                            "retention"
                        )
                        or {}
                    ),
                    "verify_after_backup": bool(
                        item[
                            "verify_after_backup"
                        ]
                    ),
                    "repository_check_schedule": dict(
                        item.get(
                            "repository_check_schedule"
                        )
                        or {}
                    ),
                    "include_deployment_config": bool(
                        item[
                            "include_deployment_config"
                        ]
                    ),
                },
            )
            applied.append(
                cls._apply_item(
                    section="backup_policies",
                    resource_type=(
                        "backup_policy"
                    ),
                    item=item,
                    action="updated",
                    target_id=target.id,
                )
            )

        alert_items = sections.get(
            "alert_policies",
            [],
        )
        assert isinstance(alert_items, list)
        for raw in alert_items:
            assert isinstance(raw, dict)
            item = raw
            match = dict(
                item.get("match")
                or {}
            )
            actions = dict(
                item.get("action")
                or {}
            )
            dependency_missing = False

            source_cameras = match.get(
                "camera_ids"
            )
            if isinstance(
                source_cameras,
                list,
            ):
                mapped_camera_ids: list[
                    str
                ] = []
                for source_id in (
                    source_cameras
                ):
                    mapped = camera_map.get(
                        str(source_id)
                    )
                    if mapped is None:
                        dependency_missing = (
                            True
                        )
                        break
                    mapped_camera_ids.append(
                        str(mapped)
                    )
                match[
                    "camera_ids"
                ] = mapped_camera_ids

            source_targets = actions.get(
                "notification_target_ids"
            )
            if (
                not dependency_missing
                and isinstance(
                    source_targets,
                    list,
                )
            ):
                mapped_target_ids: list[
                    str
                ] = []
                for source_id in (
                    source_targets
                ):
                    mapped = (
                        notification_map.get(
                            str(source_id)
                        )
                    )
                    if mapped is None:
                        dependency_missing = (
                            True
                        )
                        break
                    mapped_target_ids.append(
                        str(mapped)
                    )
                actions[
                    "notification_target_ids"
                ] = mapped_target_ids

            if dependency_missing:
                skipped.append(
                    cls._apply_item(
                        section="alert_policies",
                        resource_type=(
                            "alert_policy"
                        ),
                        item=item,
                        action="skipped",
                        reason=(
                            "alert_dependency_unmapped"
                        ),
                    )
                )
                continue

            source_uuid = cls._source_uuid(
                item
            )
            target = session.get(
                AlertPolicy,
                source_uuid,
            )
            if target is None:
                target = (
                    cls._existing_by_name(
                        session,
                        AlertPolicy,
                        str(item["name"]),
                    )
                )
            if target is None:
                target = (
                    AlertPolicyService.create(
                        session,
                        name=str(
                            item["name"]
                        ),
                        enabled=bool(
                            item["enabled"]
                        ),
                        severity=str(
                            item["severity"]
                        ),
                        match=match,
                        actions=actions,
                        cooldown_seconds=int(
                            item[
                                "cooldown_seconds"
                            ]
                        ),
                    )
                )
                action = "created"
            else:
                target = (
                    AlertPolicyService.update(
                        session,
                        policy=target,
                        changes={
                            "name": str(
                                item["name"]
                            ),
                            "enabled": bool(
                                item[
                                    "enabled"
                                ]
                            ),
                            "severity": str(
                                item[
                                    "severity"
                                ]
                            ),
                            "match": match,
                            "actions": actions,
                            "cooldown_seconds": int(
                                item[
                                    "cooldown_seconds"
                                ]
                            ),
                        },
                    )
                )
                action = "updated"
            applied.append(
                cls._apply_item(
                    section="alert_policies",
                    resource_type=(
                        "alert_policy"
                    ),
                    item=item,
                    action=action,
                    target_id=target.id,
                )
            )

        frigate = sections.get(
            "frigate"
        )
        if isinstance(frigate, dict):
            skipped.append(
                ConfigurationApplyItem(
                    section="frigate",
                    resource_type=(
                        "frigate_provider"
                    ),
                    source_id=None,
                    target_id=None,
                    name="Frigate",
                    action="skipped",
                    reason=(
                        "runtime_configuration_requires_manual_apply"
                    ),
                )
            )

        warnings = list(
            validation.warnings
        )
        warnings.append(
            (
                "Import merge never deletes target resources "
                "and never overwrites stored credential material."
            )
        )
        if skipped:
            warnings.append(
                (
                    f"{len(skipped)} resource(s) were skipped; "
                    "re-run import after resolving the reported "
                    "credential or dependency requirements."
                )
            )

        return ConfigurationApplyResult(
            applied=tuple(applied),
            skipped=tuple(skipped),
            warnings=tuple(warnings),
            camera_ids_to_reconcile=tuple(
                sorted(
                    reconcile,
                    key=str,
                )
            ),
        )
