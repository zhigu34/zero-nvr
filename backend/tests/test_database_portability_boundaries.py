from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.db.types import UTCDateTime


DOMAIN_ROOT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "modules"
)


def test_domain_modules_do_not_import_backend_specific_sqlalchemy_dialects() -> None:
    offenders: list[str] = []

    for path in DOMAIN_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "sqlalchemy.dialects." in source:
            offenders.append(
                str(path.relative_to(DOMAIN_ROOT))
            )

    assert offenders == [], (
        "Domain modules must keep SQLite/PostgreSQL-specific SQLAlchemy "
        "constructs behind small persistence/infrastructure helpers: "
        + ", ".join(sorted(offenders))
    )

def test_utc_datetime_normalizes_aware_values_and_rejects_naive() -> None:
    utc_type = UTCDateTime()

    source = datetime(
        2026,
        9,
        22,
        12,
        0,
        tzinfo=timezone(
            timedelta(hours=-7)
        ),
    )
    normalized = utc_type.process_bind_param(
        source,
        None,
    )
    assert normalized == datetime(
        2026,
        9,
        22,
        19,
        0,
        tzinfo=UTC,
    )
    assert normalized.tzinfo is UTC

    sqlite_style_value = datetime(
        2026,
        9,
        22,
        19,
        0,
    )
    loaded = utc_type.process_result_value(
        sqlite_style_value,
        None,
    )
    assert loaded == datetime(
        2026,
        9,
        22,
        19,
        0,
        tzinfo=UTC,
    )
    assert loaded.tzinfo is UTC

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        utc_type.process_bind_param(
            datetime(
                2026,
                9,
                22,
                19,
                0,
            ),
            None,
        )

