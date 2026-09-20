from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Uuid
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Portable timezone-aware UTC datetime.

    PostgreSQL keeps timezone-aware timestamps natively. SQLite's datetime
    adapter returns naive values, so the result processor re-attaches UTC.

    Public APIs still emit timezone-aware ISO 8601 values.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime requires timezone-aware datetime values")
        return value.astimezone(UTC)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


UUIDType = Uuid(as_uuid=True)


def utc_now() -> datetime:
    return datetime.now(UTC)
