"""Apply OIDC provider metadata and map default roles."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.auth.oidc import OidcProviderSettingsService

from .config_import_support import ConfigurationApplyItem


def apply_oidc_providers(
    service: type,
    session: Session,
    *,
    settings: Settings,
    sections: dict[str, Any],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    role_map: dict[str, uuid.UUID],
) -> None:
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
                service._apply_item(
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
                service._apply_item(
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
            service._apply_item(
                section="oidc_providers",
                resource_type=(
                    "oidc_provider"
                ),
                item=item,
                action="updated",
                target_id=provider.id,
            )
        )
