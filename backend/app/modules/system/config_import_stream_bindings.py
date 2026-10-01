"""Apply imported stream bindings after profile IDs are mapped."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.cameras.models import Camera
from app.modules.cameras.service import CameraService

from .config_import_support import ConfigurationApplyItem


def apply_stream_bindings(
    service: type,
    session: Session,
    *,
    settings: Settings,
    bindings: list[dict[str, Any]],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    camera_map: dict[str, uuid.UUID],
    profile_map: dict[str, uuid.UUID],
    reconcile: set[uuid.UUID],
) -> None:
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
                    service._apply_item(
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
                    service._apply_item(
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
                service._apply_item(
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

