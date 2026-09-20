from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from .database import Database


class DatabaseSchemaCompatibilityError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        current: frozenset[str],
        expected: frozenset[str],
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current = current
        self.expected = expected


@dataclass(frozen=True, slots=True)
class DatabaseSchemaStatus:
    current: frozenset[str]
    expected: frozenset[str]
    known: frozenset[str]

    @property
    def compatible(self) -> bool:
        return (
            bool(self.current)
            and self.current == self.expected
        )


@lru_cache(maxsize=1)
def _script_directory() -> ScriptDirectory:
    root = (
        Path(__file__)
        .resolve()
        .parents[3]
    )
    config = Config(
        str(root / "alembic.ini")
    )
    config.set_main_option(
        "script_location",
        str(root / "alembic"),
    )
    return ScriptDirectory.from_config(
        config
    )


@lru_cache(maxsize=1)
def expected_schema_heads() -> frozenset[str]:
    return frozenset(
        _script_directory().get_heads()
    )


@lru_cache(maxsize=1)
def known_schema_revisions() -> frozenset[str]:
    return frozenset(
        revision.revision
        for revision in (
            _script_directory().walk_revisions()
        )
    )


def current_schema_revisions(
    database: Database,
) -> frozenset[str]:
    with database.engine.connect() as connection:
        if not inspect(
            connection
        ).has_table("alembic_version"):
            return frozenset()

        values = connection.execute(
            text(
                "SELECT version_num "
                "FROM alembic_version"
            )
        ).scalars()
        return frozenset(
            str(value)
            for value in values
            if value is not None
        )


def database_schema_status(
    database: Database,
) -> DatabaseSchemaStatus:
    return DatabaseSchemaStatus(
        current=current_schema_revisions(
            database
        ),
        expected=expected_schema_heads(),
        known=known_schema_revisions(),
    )


def assert_database_schema_current(
    database: Database,
) -> DatabaseSchemaStatus:
    status = database_schema_status(
        database
    )
    if status.compatible:
        return status

    if not status.current:
        raise DatabaseSchemaCompatibilityError(
            "database_schema_uninitialized",
            (
                "Database schema is not initialized. "
                "Run the zero-nvr deployment migration command."
            ),
            current=status.current,
            expected=status.expected,
        )

    unknown = status.current - status.known
    if unknown:
        raise DatabaseSchemaCompatibilityError(
            "database_schema_unsupported",
            (
                "Database schema revision is newer or unknown "
                "to this zero-nvr version."
            ),
            current=status.current,
            expected=status.expected,
        )

    raise DatabaseSchemaCompatibilityError(
        "database_migration_required",
        (
            "Database migration is required before zero-nvr can start."
        ),
        current=status.current,
        expected=status.expected,
    )
