"""Timezone normalisation for API inputs and stored instants.

Product modules had accumulated seven private copies of "reject a naive
datetime and convert to UTC", under three different names (``_utc``,
``_normalized_utc``, ``_instant``) and with **three incompatible contracts**:

* strict, raising ``ApiError`` 422 — the intended behaviour for query and body
  parameters;
* ``None``-tolerant, returning ``None`` — needed when forwarding an optional
  filter straight from the request;
* raising a bare ``ValueError`` — one copy in ``events.system``, which surfaced
  as HTTP 500 for the same class of malformed input its twin reported as 422.

The parameter name had also drifted (``field`` vs ``field_name``), so the copies
were not substitutable. Two call sites legitimately use a different error code
(``event_timezone_required``), so ``code`` stays a parameter instead of being
hard-coded.

``utc_now`` deliberately stays in ``app.core.db.types``: it is the SQLAlchemy
column default used by ~50 models, and moving it would be a wide rename with no
behavioural benefit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.errors import ApiError

__all__ = [
    "coerce_utc",
    "optional_utc",
    "parse_aware_datetime",
    "require_utc",
]


def _is_aware(value: datetime) -> bool:
    """Return whether ``value`` carries a usable UTC offset.

    ``tzinfo is not None`` is not sufficient: a ``tzinfo`` whose ``utcoffset()``
    returns ``None`` (e.g. a mis-implemented or unlocalised zone) is still naive
    for arithmetic and comparison purposes.
    """
    return value.tzinfo is not None and value.utcoffset() is not None


def require_utc(
    value: datetime,
    *,
    field_name: str,
    code: str = "timezone_required",
) -> datetime:
    """Return ``value`` as an aware UTC datetime, rejecting naive input.

    Naive input is a client error rather than a server error: without an offset
    the instant is ambiguous, so it is reported as 422 instead of being guessed.
    """
    if not _is_aware(value):
        raise ApiError(
            status_code=422,
            code=code,
            message=f"{field_name} must include a timezone offset.",
        )
    return value.astimezone(UTC)


def optional_utc(
    value: datetime | None,
    *,
    field_name: str,
    code: str = "timezone_required",
) -> datetime | None:
    """``None``-tolerant :func:`require_utc` for optional request parameters."""
    if value is None:
        return None
    return require_utc(value, field_name=field_name, code=code)


def coerce_utc(value: datetime | None) -> datetime | None:
    """Best-effort UTC conversion that treats a naive value as already UTC.

    Only for values read back from storage: SQLite drops the offset, so a
    strictly-rejecting helper cannot be used on rows. Never use this for
    request input.
    """
    if value is None:
        return None
    if not _is_aware(value):
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_aware_datetime(value: str) -> datetime:
    """Parse an ISO 8601 string that must carry an offset.

    Used by CLI arguments, where an offset-less value from a human operator is a
    usage error rather than an ambiguous instant.
    """
    parsed = datetime.fromisoformat(value)
    if not _is_aware(parsed):
        raise ValueError(f"{value!r} must include a timezone offset")
    return parsed.astimezone(UTC)
