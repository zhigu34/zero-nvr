from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import Database
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.modules.cameras.models import (
    CameraGroup,
    CameraGroupMember,
)
from app.modules.events.models import Event
from app.modules.events.system import SystemEventService
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingProtection,
    RecordingSegment,
    RecordingTrigger,
    RetentionPolicy,
)

from .models import RecordingLocation, StorageTarget
from .service import StorageTargetService


@dataclass(frozen=True, slots=True)
class RetentionDecision:
    location_id: uuid.UUID
    segment_id: uuid.UUID
    policy_id: uuid.UUID | None
    retention_class: str
    deadline: datetime | None
    eligible_for_delete: bool
    reason: str
    archive_target_id: uuid.UUID | None = None
    pressure_override: bool = False


@dataclass(frozen=True, slots=True)
class _RetentionHorizon:
    retention_class: str
    deadline: datetime | None
    active_event: bool = False


class RetentionPlanner:
    @staticmethod
    def _single_policy(
        policies: list[RetentionPolicy],
        *,
        code: str,
    ) -> RetentionPolicy | None:
        if not policies:
            return None
        if len(policies) > 1:
            raise ApiError(
                status_code=409,
                code=code,
                message="Retention policy selection is ambiguous.",
            )
        return policies[0]

    @classmethod
    def policy_for_camera(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
    ) -> RetentionPolicy | None:
        recording_policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )
        if (
            recording_policy is not None
            and recording_policy.retention_policy_id is not None
        ):
            explicit = session.get(
                RetentionPolicy,
                recording_policy.retention_policy_id,
            )
            if explicit is None or not explicit.enabled:
                raise ApiError(
                    status_code=409,
                    code="retention_policy_unavailable",
                    message="Camera recording policy references an unavailable retention policy.",
                )
            return explicit

        camera_policies = list(
            session.scalars(
                select(RetentionPolicy).where(
                    RetentionPolicy.scope_type == "CAMERA",
                    RetentionPolicy.scope_id == camera_id,
                    RetentionPolicy.enabled.is_(True),
                )
            )
        )
        selected = cls._single_policy(
            camera_policies,
            code="retention_camera_policy_ambiguous",
        )
        if selected is not None:
            return selected

        groups = list(session.scalars(select(CameraGroup)))
        parent_by_id = {
            group.id: group.parent_id
            for group in groups
        }
        direct_group_ids = set(
            session.scalars(
                select(CameraGroupMember.camera_group_id).where(
                    CameraGroupMember.camera_id == camera_id
                )
            )
        )
        depths: dict[uuid.UUID, int] = {}
        for direct_id in direct_group_ids:
            current: uuid.UUID | None = direct_id
            depth = 0
            visited: set[uuid.UUID] = set()
            while current is not None and current not in visited:
                visited.add(current)
                previous = depths.get(current)
                if previous is None or depth < previous:
                    depths[current] = depth
                current = parent_by_id.get(current)
                depth += 1

        if depths:
            group_policies = list(
                session.scalars(
                    select(RetentionPolicy).where(
                        RetentionPolicy.scope_type
                        == "CAMERA_GROUP",
                        RetentionPolicy.scope_id.in_(
                            list(depths)
                        ),
                        RetentionPolicy.enabled.is_(True),
                    )
                )
            )
            if group_policies:
                best_depth = min(
                    depths[policy.scope_id]
                    for policy in group_policies
                    if policy.scope_id is not None
                )
                best = [
                    policy
                    for policy in group_policies
                    if policy.scope_id is not None
                    and depths[policy.scope_id] == best_depth
                ]
                selected = cls._single_policy(
                    best,
                    code="retention_group_policy_ambiguous",
                )
                if selected is not None:
                    return selected

        globals_ = list(
            session.scalars(
                select(RetentionPolicy).where(
                    RetentionPolicy.scope_type == "GLOBAL",
                    RetentionPolicy.enabled.is_(True),
                )
            )
        )
        return cls._single_policy(
            globals_,
            code="retention_global_policy_ambiguous",
        )

    @staticmethod
    def retention_class(
        segment: RecordingSegment,
    ) -> str:
        reasons = {
            str(item).lower()
            for item in (segment.recording_reasons_json or [])
        }
        if "manual" in reasons:
            return "manual"
        if "event" in reasons:
            return "event"
        return "ordinary"

    @classmethod
    def _retention_horizon(
        cls,
        session: Session,
        *,
        segment: RecordingSegment,
        policy: RetentionPolicy,
    ) -> _RetentionHorizon:
        """Derive the longest required retention from durable and live facts.

        Segment reason flags remain the compact historical facts captured at
        ingest time. Overlapping provider Events and RecordingTriggers are also
        consulted so continuous media that contains an event inherits event
        retention even when no duplicate event recording was created.
        """

        reasons = {
            str(item).lower()
            for item in (
                segment.recording_reasons_json
                or []
            )
        }
        classes = {"ordinary"}
        if "event" in reasons:
            classes.add("event")
        if "manual" in reasons:
            classes.add("manual")

        event_anchor = (
            segment.ended_at.astimezone(UTC)
        )
        active_event = False

        triggers = list(
            session.scalars(
                select(RecordingTrigger).where(
                    RecordingTrigger.camera_id
                    == segment.camera_id,
                    RecordingTrigger.state.notin_(
                        ["CANCELLED", "FAILED"]
                    ),
                    RecordingTrigger.planned_start_at
                    < segment.ended_at,
                    or_(
                        RecordingTrigger.planned_end_at
                        .is_(None),
                        RecordingTrigger.planned_end_at
                        > segment.started_at,
                    ),
                )
            )
        )
        for trigger in triggers:
            classes.add("event")
            if trigger.planned_end_at is None:
                active_event = True
                continue
            event_anchor = max(
                event_anchor,
                trigger.planned_end_at
                .astimezone(UTC),
            )

        events = list(
            session.scalars(
                select(Event).where(
                    Event.camera_id
                    == segment.camera_id,
                    Event.source
                    != SystemEventService.SOURCE,
                    Event.started_at
                    < segment.ended_at,
                    or_(
                        Event.ended_at.is_(None),
                        Event.ended_at
                        > segment.started_at,
                    ),
                )
            )
        )
        for event in events:
            classes.add("event")
            if event.ended_at is None:
                active_event = True
                continue
            event_anchor = max(
                event_anchor,
                event.ended_at.astimezone(UTC),
            )

        if active_event:
            return _RetentionHorizon(
                retention_class="event",
                deadline=None,
                active_event=True,
            )

        ended_at = segment.ended_at.astimezone(
            UTC
        )
        deadlines: dict[str, datetime] = {
            "ordinary": (
                ended_at
                + timedelta(
                    days=policy.ordinary_keep_days
                )
            )
        }
        if "event" in classes:
            deadlines["event"] = (
                event_anchor
                + timedelta(
                    days=policy.event_keep_days
                )
            )
        if "manual" in classes:
            deadlines["manual"] = (
                ended_at
                + timedelta(
                    days=policy.manual_keep_days
                )
            )

        priority = {
            "ordinary": 0,
            "event": 1,
            "manual": 2,
        }
        retention_class = max(
            deadlines,
            key=lambda item: (
                deadlines[item],
                priority[item],
            ),
        )
        return _RetentionHorizon(
            retention_class=retention_class,
            deadline=deadlines[
                retention_class
            ],
        )

    @staticmethod
    def _protected(
        session: Session,
        *,
        segment: RecordingSegment,
        now: datetime,
    ) -> bool:
        return (
            session.scalar(
                select(RecordingProtection.id)
                .where(
                    RecordingProtection.camera_id
                    == segment.camera_id,
                    RecordingProtection.started_at
                    < segment.ended_at,
                    RecordingProtection.ended_at
                    > segment.started_at,
                    or_(
                        RecordingProtection.expires_at.is_(None),
                        RecordingProtection.expires_at > now,
                    ),
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _available_archive_exists(
        session: Session,
        *,
        segment_id: uuid.UUID,
    ) -> bool:
        return (
            session.scalar(
                select(RecordingLocation.id)
                .join(
                    StorageTarget,
                    StorageTarget.id
                    == RecordingLocation.storage_target_id,
                )
                .where(
                    RecordingLocation.recording_segment_id
                    == segment_id,
                    RecordingLocation.state == "AVAILABLE",
                    StorageTarget.type == "rclone",
                    StorageTarget.role == "archive",
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _archive_target_for_retry(
        session: Session,
        *,
        segment_id: uuid.UUID,
        now: datetime,
    ) -> uuid.UUID | None:
        stale_before = now - timedelta(hours=1)
        existing = session.execute(
            select(RecordingLocation, StorageTarget)
            .join(
                StorageTarget,
                StorageTarget.id
                == RecordingLocation.storage_target_id,
            )
            .where(
                RecordingLocation.recording_segment_id
                == segment_id,
                RecordingLocation.state.in_(
                    ["ARCHIVING", "FAILED", "MISSING"]
                ),
                StorageTarget.type == "rclone",
                StorageTarget.role == "archive",
                StorageTarget.enabled.is_(True),
            )
            .order_by(
                RecordingLocation.last_attempt_at.desc(),
                RecordingLocation.id,
            )
        ).first()
        if existing is not None:
            location, target = existing
            if (
                location.state != "ARCHIVING"
                or location.last_attempt_at is None
                or location.last_attempt_at < stale_before
            ):
                return target.id
            return None

        try:
            return StorageTargetService.default_archive_target(
                session
            ).id
        except ApiError:
            return None

    @classmethod
    def evaluate(
        cls,
        session: Session,
        *,
        location: RecordingLocation,
        now: datetime | None = None,
        pressure: bool = False,
    ) -> RetentionDecision:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        segment = session.get(
            RecordingSegment,
            location.recording_segment_id,
        )
        if segment is None:
            return RetentionDecision(
                location_id=location.id,
                segment_id=location.recording_segment_id,
                policy_id=None,
                retention_class="ordinary",
                deadline=None,
                eligible_for_delete=False,
                reason="segment_missing",
            )

        target = session.get(
            StorageTarget,
            location.storage_target_id,
        )
        if (
            target is None
            or target.type != "local"
            or target.role != "recording"
            or location.state != "AVAILABLE"
        ):
            return RetentionDecision(
                location_id=location.id,
                segment_id=segment.id,
                policy_id=None,
                retention_class=cls.retention_class(segment),
                deadline=None,
                eligible_for_delete=False,
                reason="not_local_available",
            )

        if segment.timing_status != "FINAL":
            return RetentionDecision(
                location_id=location.id,
                segment_id=segment.id,
                policy_id=None,
                retention_class=(
                    cls.retention_class(
                        segment
                    )
                ),
                deadline=None,
                eligible_for_delete=False,
                reason="segment_not_final",
            )

        policy = cls.policy_for_camera(
            session,
            camera_id=segment.camera_id,
        )
        retention_class = cls.retention_class(segment)
        if policy is None:
            return RetentionDecision(
                location_id=location.id,
                segment_id=segment.id,
                policy_id=None,
                retention_class=retention_class,
                deadline=None,
                eligible_for_delete=False,
                reason="retention_policy_missing",
            )

        horizon = cls._retention_horizon(
            session,
            segment=segment,
            policy=policy,
        )
        retention_class = (
            horizon.retention_class
        )
        deadline = horizon.deadline

        if cls._protected(
            session,
            segment=segment,
            now=instant,
        ):
            return RetentionDecision(
                location_id=location.id,
                segment_id=segment.id,
                policy_id=policy.id,
                retention_class=retention_class,
                deadline=deadline,
                eligible_for_delete=False,
                reason="protected",
            )

        if horizon.active_event:
            return RetentionDecision(
                location_id=location.id,
                segment_id=segment.id,
                policy_id=policy.id,
                retention_class=retention_class,
                deadline=None,
                eligible_for_delete=False,
                reason="active_event",
            )

        assert deadline is not None
        pressure_override = (
            pressure
            and policy.mode == "BEST_EFFORT"
            and instant < deadline
        )
        if instant < deadline and not pressure_override:
            return RetentionDecision(
                location_id=location.id,
                segment_id=segment.id,
                policy_id=policy.id,
                retention_class=retention_class,
                deadline=deadline,
                eligible_for_delete=False,
                reason="before_deadline",
            )

        if (
            policy.require_archive_before_delete
            and not cls._available_archive_exists(
                session,
                segment_id=segment.id,
            )
        ):
            archive_target_id = cls._archive_target_for_retry(
                session,
                segment_id=segment.id,
                now=instant,
            )
            return RetentionDecision(
                location_id=location.id,
                segment_id=segment.id,
                policy_id=policy.id,
                retention_class=retention_class,
                deadline=deadline,
                eligible_for_delete=False,
                reason=(
                    "archive_required"
                    if archive_target_id is not None
                    else "archive_unavailable"
                ),
                archive_target_id=archive_target_id,
                pressure_override=pressure_override,
            )

        return RetentionDecision(
            location_id=location.id,
            segment_id=segment.id,
            policy_id=policy.id,
            retention_class=retention_class,
            deadline=deadline,
            eligible_for_delete=True,
            reason="eligible",
            pressure_override=pressure_override,
        )

    @classmethod
    def plan(
        cls,
        session: Session,
        *,
        now: datetime | None = None,
        pressure: bool = False,
        pressure_target_ids: set[
            uuid.UUID
        ] | None = None,
        limit: int = 500,
    ) -> list[RetentionDecision]:
        if limit < 1 or limit > 5000:
            raise ApiError(
                status_code=400,
                code="retention_limit_invalid",
                message="Retention batch limit is invalid.",
            )

        locations = list(
            session.scalars(
                select(RecordingLocation)
                .join(
                    StorageTarget,
                    StorageTarget.id
                    == RecordingLocation.storage_target_id,
                )
                .join(
                    RecordingSegment,
                    RecordingSegment.id
                    == RecordingLocation.recording_segment_id,
                )
                .where(
                    RecordingLocation.state == "AVAILABLE",
                    StorageTarget.type == "local",
                    StorageTarget.role == "recording",
                )
                .order_by(
                    RecordingSegment.ended_at,
                    RecordingLocation.id,
                )
                .limit(limit)
            )
        )
        pressured = (
            pressure_target_ids
            or set()
        )
        return [
            cls.evaluate(
                session,
                location=location,
                now=now,
                pressure=(
                    pressure
                    or location.storage_target_id
                    in pressured
                ),
            )
            for location in locations
        ]



class RetentionDeleteError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RetentionDeleteResult:
    location_id: uuid.UUID
    deleted: bool
    reason: str


class LocalRetentionDeletionService:
    """Delete only local locations already approved by RetentionPlanner."""

    @staticmethod
    def _safe_path(
        *,
        target: StorageTarget,
        object_path: str,
    ) -> Path:
        raw_root = (target.config_json or {}).get("path")
        if not isinstance(raw_root, str) or not raw_root:
            raise RetentionDeleteError(
                "retention_local_target_invalid",
                "Local recording target is invalid.",
            )

        root = Path(raw_root).expanduser().resolve(strict=False)
        candidate = (root / object_path).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RetentionDeleteError(
                "retention_local_path_invalid",
                "Local recording path is invalid.",
            ) from exc
        return candidate

    @staticmethod
    def _mark_failed(
        database: Database,
        *,
        location_id: uuid.UUID,
        error_code: str,
    ) -> None:
        with database.session() as session:
            location = session.get(
                RecordingLocation,
                location_id,
            )
            if location is not None:
                location.state = "FAILED"
                location.last_attempt_at = utc_now()
                location.last_error = error_code
                session.commit()

    @classmethod
    def execute(
        cls,
        database: Database,
        *,
        location_id: uuid.UUID,
        pressure: bool = False,
        now: datetime | None = None,
    ) -> RetentionDeleteResult:
        with database.session() as session:
            location = session.get(
                RecordingLocation,
                location_id,
            )
            if location is None:
                raise RetentionDeleteError(
                    "retention_location_missing",
                    "Recording location is unavailable.",
                )
            if location.state == "DELETED":
                session.commit()
                return RetentionDeleteResult(
                    location_id=location.id,
                    deleted=False,
                    reason="already_deleted",
                )
            if location.state != "AVAILABLE":
                session.commit()
                return RetentionDeleteResult(
                    location_id=location.id,
                    deleted=False,
                    reason="not_available",
                )

            decision = RetentionPlanner.evaluate(
                session,
                location=location,
                now=now,
                pressure=pressure,
            )
            if not decision.eligible_for_delete:
                session.commit()
                return RetentionDeleteResult(
                    location_id=location.id,
                    deleted=False,
                    reason=decision.reason,
                )

            target = session.get(
                StorageTarget,
                location.storage_target_id,
            )
            if target is None:
                raise RetentionDeleteError(
                    "retention_local_target_missing",
                    "Local recording target is unavailable.",
                )
            file_path = cls._safe_path(
                target=target,
                object_path=location.object_path,
            )
            location.state = "DELETING"
            location.last_attempt_at = utc_now()
            location.last_error = None
            session.commit()

        try:
            file_path.unlink(missing_ok=True)
        except OSError as exc:
            cls._mark_failed(
                database,
                location_id=location_id,
                error_code="retention_delete_failed",
            )
            raise RetentionDeleteError(
                "retention_delete_failed",
                "Local recording file could not be deleted.",
            ) from exc

        with database.session() as session:
            location = session.get(
                RecordingLocation,
                location_id,
            )
            if location is None:
                raise RetentionDeleteError(
                    "retention_location_missing",
                    "Recording location disappeared during deletion.",
                )
            location.state = "DELETED"
            location.deleted_at = utc_now()
            location.last_attempt_at = utc_now()
            location.last_error = None
            session.commit()

        return RetentionDeleteResult(
            location_id=location_id,
            deleted=True,
            reason="deleted",
        )
