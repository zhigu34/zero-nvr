"""Cursor pagination shared by every list endpoint.

Six modules (alerts, audit, backups, events, exports, recordings) each carried a
private copy of the same keyset-pagination codec. An AST-normalised diff showed
**no logic drift** — the copies differed only in the timestamp attribute name
and the error code — so the duplication was pure maintenance cost. It had
already produced two real inconsistencies:

* ``next_cursor`` on the response models had drifted between ``= None`` and no
  default, which changes whether the field is marked required in OpenAPI;
* ``GET /cameras/{id}/recordings`` accepted a bare ``limit: int`` while every
  sibling validated ``Query(ge=1, le=200)``, so out-of-range limits reached the
  query instead of being rejected.

The cursor is intentionally opaque base64url JSON rather than a signed token:
it encodes a ``(timestamp, id)`` keyset position, and the query still applies
the caller's authorisation filters afterwards, so a forged cursor cannot widen
the result set — it can only reposition within it.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.errors import ApiError

__all__ = [
    "PAGE_LIMIT_MAX",
    "Page",
    "decode_cursor",
    "encode_cursor",
    "normalize_page_limit",
    "paginate",
]

T = TypeVar("T")

# All list endpoints expose the same envelope, so the bound is shared rather
# than repeated per module.
PAGE_LIMIT_MAX = 200


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    """One page of a keyset-paginated list."""

    items: list[T]
    next_cursor: str | None


def encode_cursor(
    *,
    timestamp: datetime,
    identifier: uuid.UUID,
    key: str,
) -> str:
    """Encode a keyset position as an opaque cursor.

    ``key`` is the model attribute name and doubles as the JSON field, matching
    the format the per-module copies already wrote to clients.
    """
    payload = json.dumps(
        {
            key: timestamp.astimezone(UTC).isoformat(),
            "id": str(identifier),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(
    value: str,
    *,
    key: str,
    error_code: str,
    resource_label: str,
) -> tuple[datetime, uuid.UUID]:
    """Decode a cursor, reporting any malformation as a 400.

    A cursor is client-supplied, so every failure mode (bad base64, bad JSON,
    missing field, naive timestamp, malformed UUID) must become a client error
    rather than an unhandled exception.
    """
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(value + padding).decode("utf-8")
        )
        timestamp = datetime.fromisoformat(payload[key])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        return timestamp.astimezone(UTC), uuid.UUID(payload["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ApiError(
            status_code=400,
            code=error_code,
            message=f"{resource_label} cursor is invalid.",
        ) from exc


def normalize_page_limit(
    limit: int,
    *,
    error_code: str,
    resource_label: str,
    maximum: int = PAGE_LIMIT_MAX,
) -> int:
    """Validate a page size, preserving each module's own error code."""
    if limit < 1 or limit > maximum:
        raise ApiError(
            status_code=400,
            code=error_code,
            message=(
                f"{resource_label} limit must be between 1 and {maximum}."
            ),
        )
    return limit


def paginate(
    session: Session,
    statement: Any,
    *,
    timestamp_column: Any,
    id_column: Any,
    cursor: str | None,
    limit: int,
    cursor_key: str,
    cursor_error_code: str,
    resource_label: str,
) -> Page[Any]:
    """Apply the keyset filter, fetch ``limit + 1`` rows, and build a page.

    Ordering is newest-first on ``(timestamp, id)``. Fetching one extra row is
    how "is there another page" is decided without a second COUNT query.
    """
    if cursor is not None:
        timestamp, identifier = decode_cursor(
            cursor,
            key=cursor_key,
            error_code=cursor_error_code,
            resource_label=resource_label,
        )
        statement = statement.where(
            or_(
                timestamp_column < timestamp,
                and_(
                    timestamp_column == timestamp,
                    id_column < identifier,
                ),
            )
        )

    rows = list(
        session.scalars(
            statement.order_by(
                timestamp_column.desc(),
                id_column.desc(),
            ).limit(limit + 1)
        )
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(
            timestamp=getattr(last, cursor_key),
            identifier=last.id,
            key=cursor_key,
        )
    return Page(items=items, next_cursor=next_cursor)
