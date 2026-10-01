"""Application half of configuration import.

The public service facade composes this mixin with the validator and shared
readers; callers continue using ConfigurationImportService.apply().
"""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings

from .config_import_settings import apply_general_time
from .config_import_roles import apply_roles
from .config_import_devices import apply_devices
from .config_import_notifications import apply_notification_targets
from .config_import_backups import apply_backup_policies
from .config_import_alerts import apply_alert_policies
from .config_import_storage import apply_storage_targets
from .config_import_recording import apply_recording
from .config_import_cameras import apply_cameras

from .config_import_support import (
    ConfigurationApplyItem,
    ConfigurationApplyResult,
    _ImportSupport,
)


class _ImportApply:
    """Apply a validated bundle to existing resources."""

    @staticmethod
    def _source_uuid(
        item: dict[str, Any],
    ) -> uuid.UUID:
        """Read the exporter's resource id, which must be a UUID.

        This used to raise a bare ``ValueError``, which escaped the API as a
        ``500``: ``validate`` did not check the id format, so a bundle with a
        hand-written id such as ``"local"`` passed preflight and then failed
        here. Raising the module's own error keeps the failure a ``400`` with a
        code the UI already knows how to render.
        """
        raw = item.get("id")
        try:
            return uuid.UUID(str(raw))
        except (TypeError, ValueError):
            raise _ImportSupport._error(
                "configuration_import_invalid",
                "Configuration resource id must be a UUID.",
                # No JSON pointer here: the section is not known at this
                # point, so the offending id itself is what the operator needs.
                details={"id": str(raw)},
            ) from None

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

        apply_general_time(
            session, settings=settings, sections=sections, applied=applied
        )
        roles = apply_roles(
            cls, session, sections=sections, applied=applied,
            skipped=skipped, role_map=role_map,
        )

        apply_devices(
            cls, session, sections=sections, applied=applied,
            skipped=skipped, device_map=device_map,
        )

        apply_cameras(
            cls, session, settings=settings, sections=sections, roles=roles,
            applied=applied, skipped=skipped, device_map=device_map,
            role_map=role_map, camera_map=camera_map,
            profile_map=profile_map, group_map=group_map,
            reconcile=reconcile,
        )

        apply_storage_targets(
            cls, session, settings=settings, sections=sections,
            applied=applied, skipped=skipped, storage_map=storage_map,
        )
        apply_recording(
            cls, session, sections=sections, applied=applied,
            skipped=skipped, camera_map=camera_map, group_map=group_map,
            storage_map=storage_map, retention_map=retention_map,
            reconcile=reconcile,
        )

        apply_notification_targets(
            cls, session, settings=settings, sections=sections,
            applied=applied, skipped=skipped,
            notification_map=notification_map,
        )

        apply_backup_policies(
            cls, session, settings=settings, sections=sections,
            applied=applied, skipped=skipped,
        )

        apply_alert_policies(
            cls, session, sections=sections, applied=applied,
            skipped=skipped, camera_map=camera_map,
            notification_map=notification_map,
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
