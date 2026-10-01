"""Shared primitives for the configuration import service.

Split out of ``config_import.py`` so that the validator and the applier can live
in separate modules without either owning these definitions. The rules the
import format is built on belong to neither half:

* ``_FORBIDDEN_KEYS`` / ``_KNOWN_SECTIONS`` — the document's vocabulary;
* the result dataclasses both halves return;
* the readers (:meth:`_mapping`, :meth:`_items`, :meth:`_id_set`) and the
  checks (:meth:`_error`, :meth:`_reject_secret_fields`, :meth:`_require_ref`,
  :meth:`_requirement`) they are built from.

They are kept as a mixin so that every existing ``cls._error(...)`` call site in
the validator and the applier keeps working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import uuid
from typing import Any, Iterable

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



class _ImportSupport:
    """Readers and checks shared by validation and application."""

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
