"""
Per-day recording aggregates.

## Why this exists

There was no way to ask "which days have recordings, and how much" without
reading every segment row. The timeline endpoint returns segments at full
resolution regardless of its `detail` parameter
(`recordings/timeline.py:564-583`), so a month-long query on a 24/7 camera
pulls roughly 86,000 rows. The Vue files page worked around that by doing
exactly that, and then **invented** the byte total it displayed
(`FilesView.vue:262`, `dur * 450_000`) because `TimelineSegmentView` carries no
`size_bytes`.

This module aggregates in SQL instead, so the numbers are real.

## How the bucketing is done

A day is a **local** calendar day in a named IANA timezone. SQLite has no
timezone database, so `strftime` cannot do this, and a fixed UTC offset would
be wrong for the one or two hours around a DST transition. Instead the local
midnight of each day is computed in Python with `zoneinfo` and turned into a
UTC instant; the aggregation itself is then a plain range scan.

That means one aggregate query per day. For a month that is 31 bounded index
scans over `ix_recording_segments_camera_started`, which is far cheaper than
one unbounded query returning every row — and it keeps the SQL dialect-agnostic.
The range is capped in the API layer so this cannot be turned into thousands
of queries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError

from .models import RecordingSegment


@dataclass(frozen=True, slots=True)
class RecordingDayStat:
    day: str
    count: int
    duration_sec: int
    size_bytes: int


def resolve_timezone(name: str) -> ZoneInfo:
    """Reject an unknown IANA name rather than silently falling back to UTC."""
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ApiError(
            status_code=400,
            code="recording_daily_timezone_invalid",
            message="Unknown IANA timezone name.",
            details={"time_zone": name},
        ) from exc


def local_days(
    start_at: datetime,
    end_at: datetime,
    zone: ZoneInfo,
) -> list[tuple[date, datetime, datetime]]:
    """
    (local date, UTC start, UTC end) for every local day the range touches.

    The range is expanded to whole local days: a query for 09:00–17:00 still
    reports the full days it overlaps, because "how much was recorded that day"
    is a question about the day, not about the query window. Days with nothing
    recorded are omitted by the caller, so the response is a sparse list rather
    than a dense run of zeroes.
    """
    first = start_at.astimezone(zone).date() - timedelta(days=1)
    last = end_at.astimezone(zone).date() + timedelta(days=1)

    days: list[tuple[date, datetime, datetime]] = []
    cursor = first
    while cursor <= last:
        next_day = cursor + timedelta(days=1)
        # ZoneInfo resolves each local midnight to the correct UTC instant. The
        # gap between the two is used rather than assumed to be 24 hours, so a
        # spring-forward day does not swallow the following morning.
        day_start = _local_midnight_utc(cursor, zone)
        day_end = _local_midnight_utc(next_day, zone)
        days.append((cursor, day_start, day_end))
        cursor = next_day
    return days


def _local_midnight_utc(day: date, zone: ZoneInfo) -> datetime:
    return datetime(
        day.year,
        day.month,
        day.day,
        tzinfo=zone,
    ).astimezone(UTC)


class RecordingDailyQueryService:
    @staticmethod
    def list_camera_days(
        session: Session,
        *,
        camera_id: uuid.UUID,
        start_at: datetime,
        end_at: datetime,
        zone: ZoneInfo,
    ) -> list[RecordingDayStat]:
        stats: list[RecordingDayStat] = []
        for day, day_start, day_end in local_days(start_at, end_at, zone):
            row = session.execute(
                select(
                    func.count(RecordingSegment.id),
                    func.coalesce(
                        func.sum(RecordingSegment.duration_ms),
                        0,
                    ),
                    func.coalesce(
                        func.sum(RecordingSegment.size_bytes),
                        0,
                    ),
                ).where(
                    RecordingSegment.camera_id == camera_id,
                    RecordingSegment.started_at >= day_start,
                    RecordingSegment.started_at < day_end,
                )
            ).one()
            count = int(row[0] or 0)
            if count == 0:
                # Sparse on purpose: a caller drawing a calendar wants to know
                # which days have material, and a zero row per day is noise to
                # filter back out.
                continue
            stats.append(
                RecordingDayStat(
                    day=day.isoformat(),
                    count=count,
                    duration_sec=int(row[1] or 0) // 1000,
                    size_bytes=int(row[2] or 0),
                )
            )
        return stats
