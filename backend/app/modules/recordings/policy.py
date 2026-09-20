from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.cameras.models import Camera
from app.modules.recordings.models import RecordingPolicy
from app.modules.storage.models import StorageTarget

_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True, slots=True)
class WeeklyWindow:
    days: tuple[int, ...]
    start: time
    end: time


class RecordingPolicyService:
    @staticmethod
    def get(
        session: Session,
        *,
        camera_id: uuid.UUID,
    ) -> RecordingPolicy | None:
        return session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )

    @staticmethod
    def validate_schedule(
        *,
        baseline_mode: str,
        schedule_json: dict[str, object],
        schedule_timezone: str | None,
    ) -> list[WeeklyWindow]:
        if baseline_mode != "schedule":
            if schedule_json:
                raise ApiError(
                    status_code=400,
                    code="recording_schedule_not_allowed",
                    message="Schedule entries are allowed only for scheduled baseline recording.",
                )
            if schedule_timezone is not None:
                raise ApiError(
                    status_code=400,
                    code="recording_schedule_timezone_not_allowed",
                    message="Schedule timezone is allowed only for scheduled baseline recording.",
                )
            return []

        if not schedule_timezone:
            raise ApiError(
                status_code=400,
                code="recording_schedule_timezone_required",
                message="Scheduled recording requires an IANA timezone.",
            )

        try:
            ZoneInfo(schedule_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ApiError(
                status_code=400,
                code="recording_schedule_timezone_invalid",
                message="Schedule timezone is not a valid IANA timezone.",
            ) from exc

        if set(schedule_json) - {"weekly"}:
            raise ApiError(
                status_code=400,
                code="recording_schedule_invalid",
                message="Recording schedule contains unsupported fields.",
            )

        raw_windows = schedule_json.get("weekly")
        if not isinstance(raw_windows, list) or not raw_windows:
            raise ApiError(
                status_code=400,
                code="recording_schedule_required",
                message="Scheduled recording requires at least one weekly window.",
            )
        if len(raw_windows) > 64:
            raise ApiError(
                status_code=400,
                code="recording_schedule_too_large",
                message="Recording schedule has too many weekly windows.",
            )

        result: list[WeeklyWindow] = []
        for raw in raw_windows:
            if not isinstance(raw, dict) or set(raw) != {"days", "start", "end"}:
                raise ApiError(
                    status_code=400,
                    code="recording_schedule_invalid",
                    message="Each weekly window must contain days, start, and end.",
                )

            days = raw.get("days")
            start_value = raw.get("start")
            end_value = raw.get("end")
            if (
                not isinstance(days, list)
                or not days
                or not all(isinstance(day, int) and not isinstance(day, bool) for day in days)
                or not isinstance(start_value, str)
                or not isinstance(end_value, str)
                or not _TIME_RE.match(start_value)
                or not _TIME_RE.match(end_value)
            ):
                raise ApiError(
                    status_code=400,
                    code="recording_schedule_invalid",
                    message="Weekly schedule values are invalid.",
                )

            normalized_days = tuple(sorted(set(days)))
            if any(day < 0 or day > 6 for day in normalized_days):
                raise ApiError(
                    status_code=400,
                    code="recording_schedule_invalid",
                    message="Schedule days must use Monday=0 through Sunday=6.",
                )

            start = time.fromisoformat(start_value)
            end = time.fromisoformat(end_value)
            if start == end:
                raise ApiError(
                    status_code=400,
                    code="recording_schedule_invalid",
                    message="Schedule start and end times must differ.",
                )

            result.append(
                WeeklyWindow(
                    days=normalized_days,
                    start=start,
                    end=end,
                )
            )

        return result

    @classmethod
    def baseline_should_record(
        cls,
        policy: RecordingPolicy,
        *,
        at: datetime,
    ) -> bool:
        if not policy.enabled:
            return False
        if policy.baseline_mode == "continuous":
            return True
        if policy.baseline_mode == "disabled":
            return False
        if policy.baseline_mode != "schedule":
            return False

        windows = cls.validate_schedule(
            baseline_mode=policy.baseline_mode,
            schedule_json=policy.schedule_json or {},
            schedule_timezone=policy.schedule_timezone,
        )
        assert policy.schedule_timezone is not None
        local = at.astimezone(ZoneInfo(policy.schedule_timezone))
        local_time = local.timetz().replace(tzinfo=None)
        weekday = local.weekday()

        for window in windows:
            if window.start < window.end:
                if (
                    weekday in window.days
                    and window.start <= local_time < window.end
                ):
                    return True
                continue

            # Cross-midnight window. The early-morning portion belongs to the
            # previous schedule day.
            if weekday in window.days and local_time >= window.start:
                return True
            previous_day = (weekday - 1) % 7
            if previous_day in window.days and local_time < window.end:
                return True

        return False

    @staticmethod
    def validate_storage_target(
        session: Session,
        storage_target_id: uuid.UUID | None,
    ) -> None:
        if storage_target_id is None:
            return
        target = session.get(StorageTarget, storage_target_id)
        if (
            target is None
            or not target.enabled
            or target.type != "local"
            or target.role != "recording"
        ):
            raise ApiError(
                status_code=400,
                code="recording_storage_target_invalid",
                message="Recording storage target must be an enabled local recording target.",
            )

    @staticmethod
    def validate_retention_policy(
        session: Session,
        retention_policy_id: uuid.UUID | None,
    ) -> None:
        if retention_policy_id is None:
            return
        from app.modules.recordings.models import RetentionPolicy

        policy = session.get(RetentionPolicy, retention_policy_id)
        if policy is None or not policy.enabled:
            raise ApiError(
                status_code=400,
                code="retention_policy_invalid",
                message="Retention policy is unavailable.",
            )

    @classmethod
    def put(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        values: dict[str, object],
    ) -> RecordingPolicy:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise ApiError(
                status_code=404,
                code="camera_not_found",
                message="Camera was not found.",
            )

        baseline_mode = str(values["baseline_mode"])
        schedule_json = values.get("schedule_json")
        if not isinstance(schedule_json, dict):
            schedule_json = {}
        schedule_timezone = values.get("schedule_timezone")
        if schedule_timezone is not None:
            schedule_timezone = str(schedule_timezone)

        cls.validate_schedule(
            baseline_mode=baseline_mode,
            schedule_json=schedule_json,
            schedule_timezone=schedule_timezone,
        )

        storage_target_id = values.get("storage_target_id")
        retention_policy_id = values.get("retention_policy_id")
        cls.validate_storage_target(
            session,
            storage_target_id if isinstance(storage_target_id, uuid.UUID) else None,
        )
        cls.validate_retention_policy(
            session,
            retention_policy_id if isinstance(retention_policy_id, uuid.UUID) else None,
        )

        segment_target_seconds = int(values["segment_target_seconds"])
        pre_roll_seconds = int(values["pre_roll_seconds"])
        post_roll_seconds = int(values["post_roll_seconds"])
        if segment_target_seconds < 5 or segment_target_seconds > 3600:
            raise ApiError(
                status_code=400,
                code="recording_segment_target_invalid",
                message="Segment target must be between 5 and 3600 seconds.",
            )
        if pre_roll_seconds < 0 or pre_roll_seconds > 300:
            raise ApiError(
                status_code=400,
                code="recording_pre_roll_invalid",
                message="Pre-roll must be between 0 and 300 seconds.",
            )
        if post_roll_seconds < 0 or post_roll_seconds > 3600:
            raise ApiError(
                status_code=400,
                code="recording_post_roll_invalid",
                message="Post-roll must be between 0 and 3600 seconds.",
            )

        policy = cls.get(session, camera_id=camera_id)
        if policy is None:
            policy = RecordingPolicy(camera_id=camera_id)
            session.add(policy)

        policy.baseline_mode = baseline_mode
        policy.schedule_json = schedule_json
        policy.schedule_timezone = schedule_timezone
        policy.event_recording_enabled = bool(values["event_recording_enabled"])
        event_filter = values.get("event_filter_json")
        policy.event_filter_json = event_filter if isinstance(event_filter, dict) else {}
        policy.segment_target_seconds = segment_target_seconds
        policy.pre_roll_seconds = pre_roll_seconds
        policy.post_roll_seconds = post_roll_seconds
        policy.storage_target_id = (
            storage_target_id if isinstance(storage_target_id, uuid.UUID) else None
        )
        policy.retention_policy_id = (
            retention_policy_id
            if isinstance(retention_policy_id, uuid.UUID)
            else None
        )
        policy.enabled = bool(values["enabled"])
        session.flush()
        return policy



    @classmethod
    def next_baseline_transition(
        cls,
        policy: RecordingPolicy,
        *,
        after: datetime,
    ) -> datetime | None:
        """Return the next UTC wall-clock schedule boundary.

        Only the next boundary is scheduled. The Huey task schedules its
        successor after it runs, so no custom scheduler/session table exists.
        """

        if (
            not policy.enabled
            or policy.baseline_mode != "schedule"
            or not policy.schedule_timezone
        ):
            return None

        windows = cls.validate_schedule(
            baseline_mode=policy.baseline_mode,
            schedule_json=policy.schedule_json or {},
            schedule_timezone=policy.schedule_timezone,
        )
        zone = ZoneInfo(policy.schedule_timezone)
        local_after = after.astimezone(zone)
        start_date = local_after.date()

        def wall_clock(
            day: date,
            value: time,
        ) -> datetime:
            candidate = datetime.combine(
                day,
                value,
                tzinfo=zone,
            )
            # Normalize imaginary local times (spring DST gap) to the first
            # representable local instant selected by zoneinfo round-trip.
            roundtrip = candidate.astimezone(UTC).astimezone(zone)
            if (
                roundtrip.date() != day
                or roundtrip.replace(tzinfo=None).time() != value
            ):
                candidate = roundtrip
            return candidate

        candidates: list[datetime] = []
        for offset in range(0, 9):
            day = start_date + timedelta(days=offset)
            weekday = day.weekday()

            for window in windows:
                if weekday not in window.days:
                    continue

                start_local = wall_clock(day, window.start)
                candidates.append(start_local.astimezone(UTC))

                end_day = (
                    day
                    if window.start < window.end
                    else day + timedelta(days=1)
                )
                end_local = wall_clock(end_day, window.end)
                candidates.append(end_local.astimezone(UTC))

        after_utc = after.astimezone(UTC)
        future = sorted(
            candidate
            for candidate in candidates
            if candidate > after_utc
        )
        return future[0] if future else None
