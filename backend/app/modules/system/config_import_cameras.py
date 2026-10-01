"""Apply cameras, profiles, bindings, groups, and role camera scopes."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings

from .config_import_support import ConfigurationApplyItem
from .config_import_camera_matching import match_existing_camera
from .config_import_camera_metadata import update_camera_metadata
from .config_import_camera_streams import apply_camera_streams
from .config_import_camera_groups import apply_camera_groups
from .config_import_camera_scopes import apply_role_camera_scopes


def apply_cameras(
    service: type,
    session: Session,
    *,
    settings: Settings,
    sections: dict[str, Any],
    roles: list[dict[str, Any]],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    device_map: dict[str, uuid.UUID],
    role_map: dict[str, uuid.UUID],
    camera_map: dict[str, uuid.UUID],
    profile_map: dict[str, uuid.UUID],
    group_map: dict[str, uuid.UUID],
    reconcile: set[uuid.UUID],
) -> None:
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
        source_uuid = service._source_uuid(
            item
        )
        source_id = str(source_uuid)
        target = match_existing_camera(
            session, item=item, source_uuid=source_uuid,
            device_map=device_map,
        )

        if target is None:
            skipped.append(
                service._apply_item(
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

        changed, enabled_changed = update_camera_metadata(
            session, camera=target, item=item,
        )
        camera_map[source_id] = target.id
        applied.append(
            service._apply_item(
                section="cameras",
                resource_type="camera",
                item=item,
                action="updated" if changed else "matched",
                target_id=target.id,
            )
        )
        if enabled_changed:
            reconcile.add(
                target.id
            )

    apply_camera_streams(
        service, session, settings=settings, profiles=profiles,
        bindings=bindings, applied=applied, skipped=skipped,
        camera_map=camera_map, profile_map=profile_map,
        reconcile=reconcile,
    )
    apply_camera_groups(
        service, session, groups=groups, members=members,
        applied=applied, skipped=skipped, camera_map=camera_map,
        group_map=group_map,
    )
    apply_role_camera_scopes(
        service, session, roles=roles, applied=applied,
        skipped=skipped, role_map=role_map,
        camera_map=camera_map, group_map=group_map,
    )
