"""Apply imported stream profiles before their camera bindings."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings

from .config_import_support import ConfigurationApplyItem
from .config_import_stream_profiles import apply_stream_profiles
from .config_import_stream_bindings import apply_stream_bindings


def apply_camera_streams(
    service: type,
    session: Session,
    *,
    settings: Settings,
    profiles: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    camera_map: dict[str, uuid.UUID],
    profile_map: dict[str, uuid.UUID],
    reconcile: set[uuid.UUID],
) -> None:
    apply_stream_profiles(
        service, session, profiles=profiles, applied=applied,
        skipped=skipped, camera_map=camera_map, profile_map=profile_map,
    )

    apply_stream_bindings(
        service, session, settings=settings, bindings=bindings,
        applied=applied, skipped=skipped, camera_map=camera_map,
        profile_map=profile_map, reconcile=reconcile,
    )
