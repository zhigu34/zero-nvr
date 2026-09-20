from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.modules.events.models import Event
from app.modules.notifications.models import (
    NotificationDelivery,
    NotificationTarget,
)
from app.modules.recordings.models import RecordingProtection

from .models import Alert, AlertPolicy


_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_ALLOWED_MATCH_KEYS = frozenset(
    {
        "camera_ids",
        "categories",
        "labels",
        "zones",
        "min_confidence",
        "min_duration_seconds",
        "severities",
        "weekdays",
        "time_start",
        "time_end",
        "timezone",
    }
)
_ALLOWED_ACTION_KEYS = frozenset(
    {
        "notification_target_ids",
        "protect_recording",
        "protect_before_seconds",
        "protect_after_seconds",
        "protect_expires_days",
    }
)
_ALERT_SEVERITIES = frozenset(
    {"info", "warning", "critical"}
)


@dataclass(frozen=True, slots=True)
class AlertEvaluationResult:
    alerts: tuple[Alert, ...]
    delivery_ids: tuple[uuid.UUID, ...]


class AlertPolicyService:
    @staticmethod
    def list(session: Session) -> list[AlertPolicy]:
        return list(
            session.scalars(
                select(AlertPolicy).order_by(
                    AlertPolicy.name,
                    AlertPolicy.id,
                )
            )
        )

    @staticmethod
    def get(
        session: Session,
        policy_id: uuid.UUID,
    ) -> AlertPolicy:
        policy = session.get(AlertPolicy, policy_id)
        if policy is None:
            raise ApiError(
                status_code=404,
                code="alert_policy_not_found",
                message="Alert policy was not found.",
            )
        return policy

    @staticmethod
    def delete(
        session: Session,
        *,
        policy: AlertPolicy,
    ) -> None:
        session.delete(policy)
        session.flush()

    @staticmethod
    def _uuid_list(
        value: object,
        *,
        field_name: str,
        max_items: int = 256,
    ) -> list[uuid.UUID]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ApiError(
                status_code=400,
                code="alert_policy_match_invalid",
                message=f"{field_name} must be a list.",
            )
        if len(value) > max_items:
            raise ApiError(
                status_code=400,
                code="alert_policy_match_invalid",
                message=f"{field_name} contains too many items.",
            )
        result: list[uuid.UUID] = []
        for raw in value:
            try:
                parsed = uuid.UUID(str(raw))
            except (TypeError, ValueError) as exc:
                raise ApiError(
                    status_code=400,
                    code="alert_policy_match_invalid",
                    message=f"{field_name} contains an invalid UUID.",
                ) from exc
            if parsed not in result:
                result.append(parsed)
        return result

    @staticmethod
    def _string_list(
        value: object,
        *,
        field_name: str,
        max_length: int = 128,
        max_items: int = 128,
    ) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ApiError(
                status_code=400,
                code="alert_policy_match_invalid",
                message=f"{field_name} must be a list.",
            )
        if len(value) > max_items:
            raise ApiError(
                status_code=400,
                code="alert_policy_match_invalid",
                message=f"{field_name} contains too many items.",
            )
        result: list[str] = []
        for raw in value:
            if not isinstance(raw, str):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_match_invalid",
                    message=f"{field_name} contains an invalid value.",
                )
            normalized = raw.strip()
            if (
                not normalized
                or len(normalized) > max_length
            ):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_match_invalid",
                    message=f"{field_name} contains an invalid value.",
                )
            if normalized not in result:
                result.append(normalized)
        return result

    @classmethod
    def normalize_match(
        cls,
        session: Session,
        value: dict[str, object],
    ) -> dict[str, object]:
        if set(value) - _ALLOWED_MATCH_KEYS:
            raise ApiError(
                status_code=400,
                code="alert_policy_match_invalid",
                message="Alert policy contains unsupported match fields.",
            )

        result: dict[str, object] = {}

        camera_ids = cls._uuid_list(
            value.get("camera_ids"),
            field_name="camera_ids",
        )
        if camera_ids:
            from app.modules.cameras.models import Camera

            found = set(
                session.scalars(
                    select(Camera.id).where(
                        Camera.id.in_(camera_ids)
                    )
                )
            )
            missing = set(camera_ids) - found
            if missing:
                raise ApiError(
                    status_code=400,
                    code="alert_policy_camera_invalid",
                    message="Alert policy references an unknown camera.",
                )
            result["camera_ids"] = [
                str(item) for item in camera_ids
            ]

        for key, max_length in (
            ("categories", 64),
            ("labels", 128),
            ("zones", 128),
            ("severities", 32),
        ):
            items = cls._string_list(
                value.get(key),
                field_name=key,
                max_length=max_length,
            )
            if items:
                result[key] = items

        severities = result.get("severities")
        if isinstance(severities, list) and any(
            item not in _ALERT_SEVERITIES
            for item in severities
        ):
            raise ApiError(
                status_code=400,
                code="alert_policy_match_invalid",
                message="Alert policy event severity is invalid.",
            )

        min_confidence = value.get("min_confidence")
        if min_confidence is not None:
            if (
                isinstance(min_confidence, bool)
                or not isinstance(
                    min_confidence,
                    (int, float),
                )
                or not 0 <= float(min_confidence) <= 1
            ):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_match_invalid",
                    message="Minimum confidence must be between 0 and 1.",
                )
            result["min_confidence"] = float(
                min_confidence
            )

        min_duration = value.get(
            "min_duration_seconds"
        )
        if min_duration is not None:
            if (
                isinstance(min_duration, bool)
                or not isinstance(
                    min_duration,
                    (int, float),
                )
                or not 0 <= float(min_duration) <= 86400
            ):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_match_invalid",
                    message="Minimum duration is invalid.",
                )
            result["min_duration_seconds"] = float(
                min_duration
            )

        weekdays = value.get("weekdays")
        if weekdays is not None:
            if (
                not isinstance(weekdays, list)
                or not weekdays
                or not all(
                    isinstance(item, int)
                    and not isinstance(item, bool)
                    and 0 <= item <= 6
                    for item in weekdays
                )
            ):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_match_invalid",
                    message="Weekdays must use Monday=0 through Sunday=6.",
                )
            result["weekdays"] = sorted(
                set(weekdays)
            )

        time_start = value.get("time_start")
        time_end = value.get("time_end")
        timezone = value.get("timezone")
        has_time_filter = (
            time_start is not None
            or time_end is not None
            or timezone is not None
        )
        if has_time_filter:
            if (
                not isinstance(time_start, str)
                or not isinstance(time_end, str)
                or not _TIME_RE.fullmatch(time_start)
                or not _TIME_RE.fullmatch(time_end)
                or time_start == time_end
                or not isinstance(timezone, str)
                or not timezone.strip()
            ):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_match_invalid",
                    message="Alert policy time window is invalid.",
                )
            try:
                ZoneInfo(timezone.strip())
            except ZoneInfoNotFoundError as exc:
                raise ApiError(
                    status_code=400,
                    code="alert_policy_match_invalid",
                    message="Alert policy timezone is invalid.",
                ) from exc
            result["time_start"] = time_start
            result["time_end"] = time_end
            result["timezone"] = timezone.strip()

        return result

    @classmethod
    def normalize_actions(
        cls,
        session: Session,
        value: dict[str, object],
    ) -> dict[str, object]:
        if set(value) - _ALLOWED_ACTION_KEYS:
            raise ApiError(
                status_code=400,
                code="alert_policy_action_invalid",
                message="Alert policy contains unsupported actions.",
            )

        result: dict[str, object] = {}
        target_ids = cls._uuid_list(
            value.get("notification_target_ids"),
            field_name="notification_target_ids",
        )
        if target_ids:
            found = set(
                session.scalars(
                    select(NotificationTarget.id).where(
                        NotificationTarget.id.in_(
                            target_ids
                        )
                    )
                )
            )
            if set(target_ids) - found:
                raise ApiError(
                    status_code=400,
                    code="alert_policy_notification_target_invalid",
                    message="Alert policy references an unknown notification target.",
                )
            result["notification_target_ids"] = [
                str(item) for item in target_ids
            ]

        protect = bool(
            value.get("protect_recording", False)
        )
        result["protect_recording"] = protect

        for key, maximum in (
            ("protect_before_seconds", 3600),
            ("protect_after_seconds", 86400),
            ("protect_expires_days", 36500),
        ):
            raw = value.get(key, 0)
            if (
                isinstance(raw, bool)
                or not isinstance(raw, int)
                or raw < 0
                or raw > maximum
            ):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_action_invalid",
                    message=f"{key} is invalid.",
                )
            if raw:
                result[key] = raw

        if not protect and any(
            key in result
            for key in (
                "protect_before_seconds",
                "protect_after_seconds",
                "protect_expires_days",
            )
        ):
            raise ApiError(
                status_code=400,
                code="alert_policy_action_invalid",
                message="Recording protection timing requires protect_recording=true.",
            )

        return result

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        name: str,
        enabled: bool,
        severity: str,
        match: dict[str, object],
        actions: dict[str, object],
        cooldown_seconds: int,
    ) -> AlertPolicy:
        normalized_name = name.strip()
        if not normalized_name:
            raise ApiError(
                status_code=400,
                code="alert_policy_name_invalid",
                message="Alert policy name is invalid.",
            )
        if session.scalar(
            select(AlertPolicy.id)
            .where(AlertPolicy.name == normalized_name)
            .limit(1)
        ) is not None:
            raise ApiError(
                status_code=409,
                code="alert_policy_name_conflict",
                message="Alert policy name is already in use.",
            )
        normalized_severity = severity.strip().lower()
        if normalized_severity not in _ALERT_SEVERITIES:
            raise ApiError(
                status_code=400,
                code="alert_policy_severity_invalid",
                message="Alert policy severity is invalid.",
            )
        if (
            isinstance(cooldown_seconds, bool)
            or cooldown_seconds < 0
            or cooldown_seconds > 604800
        ):
            raise ApiError(
                status_code=400,
                code="alert_policy_cooldown_invalid",
                message="Alert policy cooldown is invalid.",
            )

        policy = AlertPolicy(
            name=normalized_name,
            enabled=enabled,
            severity=normalized_severity,
            match_json=cls.normalize_match(
                session,
                match,
            ),
            action_json=cls.normalize_actions(
                session,
                actions,
            ),
            cooldown_seconds=cooldown_seconds,
        )
        session.add(policy)
        session.flush()
        return policy

    @classmethod
    def update(
        cls,
        session: Session,
        *,
        policy: AlertPolicy,
        changes: dict[str, object],
    ) -> AlertPolicy:
        if "name" in changes:
            raw_name = changes["name"]
            if (
                not isinstance(raw_name, str)
                or not raw_name.strip()
            ):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_name_invalid",
                    message="Alert policy name is invalid.",
                )
            normalized_name = raw_name.strip()
            conflict = session.scalar(
                select(AlertPolicy.id)
                .where(
                    AlertPolicy.name == normalized_name,
                    AlertPolicy.id != policy.id,
                )
                .limit(1)
            )
            if conflict is not None:
                raise ApiError(
                    status_code=409,
                    code="alert_policy_name_conflict",
                    message="Alert policy name is already in use.",
                )
            policy.name = normalized_name

        if "enabled" in changes:
            policy.enabled = bool(changes["enabled"])

        if "severity" in changes:
            raw = changes["severity"]
            if not isinstance(raw, str):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_severity_invalid",
                    message="Alert policy severity is invalid.",
                )
            normalized = raw.strip().lower()
            if normalized not in _ALERT_SEVERITIES:
                raise ApiError(
                    status_code=400,
                    code="alert_policy_severity_invalid",
                    message="Alert policy severity is invalid.",
                )
            policy.severity = normalized

        if "match" in changes:
            raw_match = changes["match"]
            if not isinstance(raw_match, dict):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_match_invalid",
                    message="Alert policy match is invalid.",
                )
            policy.match_json = cls.normalize_match(
                session,
                raw_match,
            )

        if "actions" in changes:
            raw_actions = changes["actions"]
            if not isinstance(raw_actions, dict):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_action_invalid",
                    message="Alert policy actions are invalid.",
                )
            policy.action_json = cls.normalize_actions(
                session,
                raw_actions,
            )

        if "cooldown_seconds" in changes:
            raw_cooldown = changes["cooldown_seconds"]
            if (
                isinstance(raw_cooldown, bool)
                or not isinstance(raw_cooldown, int)
                or raw_cooldown < 0
                or raw_cooldown > 604800
            ):
                raise ApiError(
                    status_code=400,
                    code="alert_policy_cooldown_invalid",
                    message="Alert policy cooldown is invalid.",
                )
            policy.cooldown_seconds = raw_cooldown

        session.flush()
        return policy


class AlertEvaluationService:
    @staticmethod
    def _time_match(
        match: dict[str, object],
        event: Event,
    ) -> bool:
        timezone = match.get("timezone")
        if not isinstance(timezone, str):
            return True

        local = event.started_at.astimezone(
            ZoneInfo(timezone)
        )
        weekdays = match.get("weekdays")
        if (
            isinstance(weekdays, list)
            and local.weekday() not in weekdays
        ):
            return False

        start_raw = match.get("time_start")
        end_raw = match.get("time_end")
        if not (
            isinstance(start_raw, str)
            and isinstance(end_raw, str)
        ):
            return True

        start = time.fromisoformat(start_raw)
        end = time.fromisoformat(end_raw)
        current = local.timetz().replace(tzinfo=None)
        if start < end:
            return start <= current < end
        return current >= start or current < end

    @classmethod
    def matches(
        cls,
        policy: AlertPolicy,
        event: Event,
    ) -> bool:
        if not policy.enabled:
            return False
        match = policy.match_json or {}

        camera_ids = match.get("camera_ids")
        if isinstance(camera_ids, list):
            if (
                event.camera_id is None
                or str(event.camera_id) not in camera_ids
            ):
                return False

        mapping = (
            ("categories", event.category),
            ("labels", event.label),
            ("zones", event.zone),
            ("severities", event.severity),
        )
        for key, value in mapping:
            allowed = match.get(key)
            if (
                isinstance(allowed, list)
                and value not in allowed
            ):
                return False

        minimum = match.get("min_confidence")
        if isinstance(minimum, (int, float)):
            if (
                event.confidence is None
                or event.confidence < float(minimum)
            ):
                return False

        minimum_duration = match.get(
            "min_duration_seconds"
        )
        if isinstance(
            minimum_duration,
            (int, float),
        ):
            if event.ended_at is None:
                return False
            duration = (
                event.ended_at - event.started_at
            ).total_seconds()
            if duration < float(minimum_duration):
                return False

        if not cls._time_match(match, event):
            return False

        return True

    @staticmethod
    def _cooldown_blocked(
        session: Session,
        *,
        policy: AlertPolicy,
        event: Event,
    ) -> bool:
        if policy.cooldown_seconds <= 0:
            return False

        boundary = event.started_at - timedelta(
            seconds=policy.cooldown_seconds
        )
        from app.modules.events.models import Event as EventModel

        statement = (
            select(Alert.id)
            .join(
                EventModel,
                EventModel.id == Alert.event_id,
            )
            .where(
                Alert.policy_id == policy.id,
                EventModel.started_at >= boundary,
                EventModel.started_at < event.started_at,
            )
            .limit(1)
        )
        if event.camera_id is None:
            statement = statement.where(
                Alert.camera_id.is_(None)
            )
        else:
            statement = statement.where(
                Alert.camera_id == event.camera_id
            )
        return session.scalar(statement) is not None

    @staticmethod
    def _title(event: Event) -> str:
        subject = (
            event.label
            or event.category
            or "event"
        )
        return f"{subject} detected"[:256]

    @staticmethod
    def _body(event: Event) -> str:
        parts = [
            f"source={event.source}",
            f"category={event.category}",
        ]
        if event.label:
            parts.append(f"label={event.label}")
        if event.zone:
            parts.append(f"zone={event.zone}")
        if event.confidence is not None:
            parts.append(
                f"confidence={event.confidence:.3f}"
            )
        parts.append(
            f"started_at={event.started_at.astimezone(UTC).isoformat()}"
        )
        return "\n".join(parts)

    @classmethod
    def evaluate_event(
        cls,
        session: Session,
        *,
        event: Event,
    ) -> AlertEvaluationResult:
        created_alerts: list[Alert] = []
        delivery_ids: list[uuid.UUID] = []

        policies = list(
            session.scalars(
                select(AlertPolicy)
                .where(AlertPolicy.enabled.is_(True))
                .order_by(AlertPolicy.id)
            )
        )

        for policy in policies:
            if not cls.matches(policy, event):
                continue

            existing = session.scalar(
                select(Alert).where(
                    Alert.policy_id == policy.id,
                    Alert.event_id == event.id,
                )
            )
            if existing is not None:
                continue

            if cls._cooldown_blocked(
                session,
                policy=policy,
                event=event,
            ):
                continue

            alert = Alert(
                policy_id=policy.id,
                event_id=event.id,
                camera_id=event.camera_id,
                severity=policy.severity,
                title=cls._title(event),
                message=cls._body(event),
                state="OPEN",
            )
            session.add(alert)
            session.flush()
            created_alerts.append(alert)

            actions = policy.action_json or {}
            raw_targets = actions.get(
                "notification_target_ids"
            )
            if isinstance(raw_targets, list):
                for raw_target in raw_targets:
                    try:
                        target_id = uuid.UUID(
                            str(raw_target)
                        )
                    except ValueError:
                        continue
                    target = session.get(
                        NotificationTarget,
                        target_id,
                    )
                    if (
                        target is None
                        or not target.enabled
                    ):
                        continue
                    delivery = NotificationDelivery(
                        alert_id=alert.id,
                        notification_target_id=target.id,
                        state="PENDING",
                        attempts=0,
                        title=alert.title,
                        body=alert.message or alert.title,
                    )
                    session.add(delivery)
                    session.flush()
                    delivery_ids.append(delivery.id)

            if (
                bool(
                    actions.get(
                        "protect_recording",
                        False,
                    )
                )
                and event.camera_id is not None
            ):
                before = int(
                    actions.get(
                        "protect_before_seconds",
                        0,
                    )
                )
                after = int(
                    actions.get(
                        "protect_after_seconds",
                        0,
                    )
                )
                expires_days = int(
                    actions.get(
                        "protect_expires_days",
                        0,
                    )
                )
                end = event.ended_at or event.started_at
                protection = RecordingProtection(
                    camera_id=event.camera_id,
                    started_at=event.started_at
                    - timedelta(seconds=before),
                    ended_at=end
                    + timedelta(seconds=after),
                    reason=f"alert:{alert.id}",
                    expires_at=(
                        utc_now()
                        + timedelta(days=expires_days)
                        if expires_days > 0
                        else None
                    ),
                )
                session.add(protection)

        session.flush()
        return AlertEvaluationResult(
            alerts=tuple(created_alerts),
            delivery_ids=tuple(delivery_ids),
        )
