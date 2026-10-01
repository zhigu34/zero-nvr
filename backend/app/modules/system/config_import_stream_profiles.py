"""Match imported camera stream profiles to local profiles with secrets."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.cameras.models import CameraStreamProfile

from .config_import_support import ConfigurationApplyItem


def apply_stream_profiles(
    service: type,
    session: Session,
    *,
    profiles: list[dict[str, Any]],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    camera_map: dict[str, uuid.UUID],
    profile_map: dict[str, uuid.UUID],
) -> None:
    for raw in profiles:
        assert isinstance(raw, dict)
        item = raw
        source_uuid = service._source_uuid(
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
                service._apply_item(
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
                service._apply_item(
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
            service._apply_item(
                section="cameras",
                resource_type=(
                    "camera_stream_profile"
                ),
                item=item,
                action="matched",
                target_id=target.id,
            )
        )
