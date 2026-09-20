from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.core.config import Settings
from app.core.errors import ApiError


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
            cls._require_ref(
                item.get("device_id"),
                device_ids,
                path=(
                    "$.sections.cameras.cameras"
                    f"[{index}].device_id"
                ),
                nullable=True,
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
