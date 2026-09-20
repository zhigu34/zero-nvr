from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.cameras.models import Camera

from .models import RecordingPolicy, RecordingTrigger


class RecordingTriggerService:
    @staticmethod
    def get(
        session: Session,
        trigger_id: uuid.UUID,
    ) -> RecordingTrigger:
        trigger = session.get(RecordingTrigger, trigger_id)
        if trigger is None:
            raise ApiError(
                status_code=404,
                code="recording_trigger_not_found",
                message="Recording trigger was not found.",
            )
        return trigger

    @staticmethod
    def list_for_camera(
        session: Session,
        *,
        camera_id: uuid.UUID,
        limit: int = 100,
    ) -> list[RecordingTrigger]:
        return list(
            session.scalars(
                select(RecordingTrigger)
                .where(
                    RecordingTrigger.camera_id == camera_id
                )
                .order_by(
                    RecordingTrigger.requested_at.desc(),
                    RecordingTrigger.id.desc(),
                )
                .limit(limit)
            )
        )

    @staticmethod
    def _policy(
        session: Session,
        *,
        camera_id: uuid.UUID,
    ) -> RecordingPolicy:
        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )
        if (
            policy is None
            or not policy.enabled
            or not policy.event_recording_enabled
        ):
            raise ApiError(
                status_code=409,
                code="event_recording_not_enabled",
                message="Event recording is not enabled for this camera.",
            )
        return policy

    @staticmethod
    def _event_matches(
        policy: RecordingPolicy,
        *,
        label: str | None,
        confidence: float | None,
        zones: list[str],
    ) -> bool:
        event_filter = policy.event_filter_json or {}

        labels = event_filter.get("labels")
        if isinstance(labels, list) and labels:
            if label not in labels:
                return False

        required_zones = event_filter.get("zones")
        if isinstance(required_zones, list) and required_zones:
            if not set(required_zones).intersection(zones):
                return False

        minimum = event_filter.get("min_confidence")
        if isinstance(minimum, (int, float)):
            if confidence is None or confidence < float(minimum):
                return False

        return True

    @classmethod
    def upsert_provider(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        source: str,
        source_instance_id: str,
        source_event_id: str,
        event_started_at: datetime,
        event_ended_at: datetime | None,
        trigger_type: str,
        reason: str | None,
        label: str | None,
        confidence: float | None,
        zones: list[str],
        metadata: dict[str, object] | None = None,
    ) -> tuple[RecordingTrigger | None, bool]:
        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )
        if (
            policy is None
            or not policy.enabled
            or not policy.event_recording_enabled
        ):
            return None, False

        provider_identity = (
            f"{source_instance_id}:{source_event_id}"
        )
        if len(provider_identity) > 512:
            raise ApiError(
                status_code=422,
                code="recording_trigger_identity_too_long",
                message="Provider recording trigger identity is too long.",
            )

        existing = session.scalar(
            select(RecordingTrigger).where(
                RecordingTrigger.source == source,
                RecordingTrigger.source_event_id
                == provider_identity,
            )
        )

        if existing is None and not cls._event_matches(
            policy,
            label=label,
            confidence=confidence,
            zones=zones,
        ):
            return None, False

        if existing is None:
            correlation_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                (
                    f"zero-nvr/recording-trigger/"
                    f"{source}/{provider_identity}"
                ),
            ).hex
            trigger = RecordingTrigger(
                camera_id=camera_id,
                type=trigger_type,
                source=source,
                source_event_id=provider_identity,
                requested_at=event_started_at,
                pre_roll_seconds=policy.pre_roll_seconds,
                post_roll_seconds=policy.post_roll_seconds,
                planned_start_at=event_started_at
                - timedelta(seconds=policy.pre_roll_seconds),
                planned_end_at=(
                    event_ended_at
                    + timedelta(
                        seconds=policy.post_roll_seconds
                    )
                    if event_ended_at is not None
                    else None
                ),
                state=(
                    "COMPLETED"
                    if event_ended_at is not None
                    else "ACTIVE"
                ),
                reason=reason,
                correlation_id=correlation_id,
                metadata_json=dict(metadata or {}),
            )
            session.add(trigger)
            session.flush()
            return trigger, True

        if existing.camera_id != camera_id:
            raise ApiError(
                status_code=409,
                code="recording_trigger_camera_conflict",
                message="Provider recording trigger is already mapped to another camera.",
            )

        changed = False
        if event_ended_at is not None:
            planned_end = event_ended_at + timedelta(
                seconds=existing.post_roll_seconds
            )
            if (
                existing.planned_end_at is None
                or planned_end > existing.planned_end_at
            ):
                existing.planned_end_at = planned_end
                changed = True
            if existing.state != "COMPLETED":
                existing.state = "COMPLETED"
                changed = True

        if metadata is not None:
            new_metadata = dict(metadata)
            if existing.metadata_json != new_metadata:
                existing.metadata_json = new_metadata
                changed = True

        if reason and existing.reason != reason:
            existing.reason = reason
            changed = True

        if changed:
            session.flush()
        return existing, changed

    @classmethod
    def create_manual(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        requested_at: datetime | None = None,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[RecordingTrigger, bool]:
        if session.get(Camera, camera_id) is None:
            raise ApiError(
                status_code=404,
                code="camera_not_found",
                message="Camera was not found.",
            )

        policy = cls._policy(
            session,
            camera_id=camera_id,
        )
        now = requested_at or datetime.now(UTC)

        source_event_id: str | None = None
        if idempotency_key:
            normalized = idempotency_key.strip()
            if not normalized or len(normalized) > 256:
                raise ApiError(
                    status_code=400,
                    code="idempotency_key_invalid",
                    message="Idempotency-Key must be 1 to 256 characters.",
                )
            source_event_id = f"{camera_id}:{normalized}"
            existing = session.scalar(
                select(RecordingTrigger).where(
                    RecordingTrigger.source == "api",
                    RecordingTrigger.source_event_id
                    == source_event_id,
                )
            )
            if existing is not None:
                return existing, False

        trigger = RecordingTrigger(
            camera_id=camera_id,
            type="MANUAL",
            source="api",
            source_event_id=source_event_id,
            requested_at=now,
            pre_roll_seconds=policy.pre_roll_seconds,
            post_roll_seconds=policy.post_roll_seconds,
            planned_start_at=now
            - timedelta(seconds=policy.pre_roll_seconds),
            planned_end_at=None,
            state="ACTIVE",
            reason=reason,
            correlation_id=uuid.uuid4().hex,
            metadata_json={},
        )
        session.add(trigger)
        session.flush()
        return trigger, True

    @staticmethod
    def close_active_manual_for_camera(
        session: Session,
        *,
        camera_id: uuid.UUID,
        stopped_at: datetime | None = None,
    ) -> int:
        now = stopped_at or datetime.now(UTC)
        items = list(
            session.scalars(
                select(RecordingTrigger).where(
                    RecordingTrigger.camera_id == camera_id,
                    RecordingTrigger.type == "MANUAL",
                    RecordingTrigger.state == "ACTIVE",
                    RecordingTrigger.planned_end_at.is_(None),
                )
            )
        )
        for trigger in items:
            trigger.planned_end_at = max(
                now,
                trigger.planned_start_at,
            )
            trigger.state = "COMPLETED"
        if items:
            session.flush()
        return len(items)

    @classmethod
    def stop_manual(
        cls,
        session: Session,
        *,
        trigger: RecordingTrigger,
        stopped_at: datetime | None = None,
    ) -> RecordingTrigger:
        if trigger.state in {"CANCELLED", "FAILED"}:
            raise ApiError(
                status_code=409,
                code="recording_trigger_not_active",
                message="Recording trigger cannot be stopped.",
            )

        if trigger.planned_end_at is not None:
            return trigger

        now = stopped_at or datetime.now(UTC)
        trigger.planned_end_at = now + timedelta(
            seconds=trigger.post_roll_seconds
        )
        trigger.state = "COMPLETED"
        session.flush()
        return trigger

    @staticmethod
    def overlaps_fragment(
        session: Session,
        *,
        camera_id: uuid.UUID,
        started_at: datetime,
        ended_at: datetime,
    ) -> bool:
        return (
            session.scalar(
                select(RecordingTrigger.id)
                .where(
                    RecordingTrigger.camera_id == camera_id,
                    RecordingTrigger.state.notin_(
                        ["CANCELLED", "FAILED"]
                    ),
                    RecordingTrigger.planned_start_at < ended_at,
                    or_(
                        RecordingTrigger.planned_end_at.is_(None),
                        RecordingTrigger.planned_end_at > started_at,
                    ),
                )
                .limit(1)
            )
            is not None
        )
