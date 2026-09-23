from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Database
from app.integrations.zlm import (
    ZlmAdapter,
    ZlmContinuityTracker,
    ZlmObservedHealthStore,
)

from .media_runtime import CameraMediaRuntimeService
from .models import CameraStreamBinding


@dataclass(frozen=True, slots=True)
class ZlmRuntimeObservationResult:
    profiles: int
    online: int
    recording: int


class ZlmRuntimeObservationService:
    """Rebuild process-local ZLM observations after control-plane restart."""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        *,
        health: ZlmObservedHealthStore,
        continuity: ZlmContinuityTracker,
        adapter_factory: Callable[
            [Settings],
            Any,
        ] = ZlmAdapter,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.health = health
        self.continuity = continuity
        self._adapter_factory = adapter_factory
        self._now = (
            now
            if now is not None
            else lambda: datetime.now(UTC)
        )

    @staticmethod
    def _created_at(
        item: dict[str, Any],
        *,
        fallback: datetime,
    ) -> datetime:
        raw = item.get("createStamp")
        if isinstance(raw, (int, float)) and raw > 0:
            try:
                return datetime.fromtimestamp(
                    float(raw),
                    tz=UTC,
                )
            except (
                OverflowError,
                OSError,
                ValueError,
            ):
                pass
        return fallback

    def rebuild(self) -> ZlmRuntimeObservationResult:
        with self.database.session() as session:
            profile_ids = sorted(
                set(
                    session.scalars(
                        select(
                            CameraStreamBinding.stream_profile_id
                        )
                    )
                ),
                key=str,
            )
            session.commit()

        observed_at = self._now()
        online_count = 0
        recording_count = 0

        with self._adapter_factory(self.settings) as zlm:
            for profile_id in profile_ids:
                stream = f"profile-{profile_id.hex}"
                items = zlm.get_media_list(
                    app=CameraMediaRuntimeService.app_name,
                    stream=stream,
                    schema="rtsp",
                )
                if not items:
                    continuity_id = self.continuity.unregistered(
                        vhost="__defaultVhost__",
                        app=CameraMediaRuntimeService.app_name,
                        stream=stream,
                        at=observed_at,
                    )
                    self.health.stream_unregistered(
                        profile_id,
                        at=observed_at,
                        continuity_id=continuity_id,
                    )
                    self.health.recording_observed(
                        profile_id,
                        active=False,
                        at=observed_at,
                        continuity_id=continuity_id,
                    )
                    continue

                online_count += 1
                item = items[0]
                opened_at = self._created_at(
                    item,
                    fallback=observed_at,
                )
                continuity_id = self.continuity.registered(
                    vhost="__defaultVhost__",
                    app=CameraMediaRuntimeService.app_name,
                    stream=stream,
                    at=opened_at,
                )
                self.health.stream_registered(
                    profile_id,
                    at=observed_at,
                    continuity_id=continuity_id,
                )
                active = any(
                    bool(
                        candidate.get(
                            "isRecordingMP4",
                            False,
                        )
                    )
                    for candidate in items
                )
                if active:
                    recording_count += 1
                self.health.recording_observed(
                    profile_id,
                    active=active,
                    at=observed_at,
                    continuity_id=continuity_id,
                )

        return ZlmRuntimeObservationResult(
            profiles=len(profile_ids),
            online=online_count,
            recording=recording_count,
        )
