from __future__ import annotations

from pathlib import Path


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
