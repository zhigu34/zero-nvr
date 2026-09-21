from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import DateTime, text

from app.core.config import Settings
from app.core.db import (
    Base,
    Database,
    DatabaseSchemaCompatibilityError,
    assert_database_schema_current,
    expected_schema_heads,
    known_schema_revisions,
)
from app.core.db.types import UTCDateTime
from app.main import create_app


def make_database(
    tmp_path: Path,
) -> Database:
    settings = Settings(
        secret_key=(
            "schema-guard-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="production",
        database_url=(
            f"sqlite:///{tmp_path / 'schema.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(
        database.engine
    )
    return database


def stamp(
    database: Database,
    revision: str,
) -> None:
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS "
                "alembic_version ("
                "version_num VARCHAR(32) "
                "NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "DELETE FROM alembic_version"
            )
        )
        connection.execute(
            text(
                "INSERT INTO alembic_version "
                "(version_num) VALUES (:revision)"
            ),
            {"revision": revision},
        )


def test_schema_guard_rejects_uninitialized_database(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    try:
        with pytest.raises(
            DatabaseSchemaCompatibilityError
        ) as captured:
            assert_database_schema_current(
                database
            )
        assert (
            captured.value.code
            == "database_schema_uninitialized"
        )
    finally:
        database.close()


def test_schema_guard_accepts_current_head(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    try:
        heads = expected_schema_heads()
        assert len(heads) == 1
        stamp(database, next(iter(heads)))

        status = (
            assert_database_schema_current(
                database
            )
        )
        assert status.compatible is True
        assert status.current == heads
    finally:
        database.close()


def test_schema_guard_distinguishes_old_and_unknown_revision(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    try:
        heads = expected_schema_heads()
        older = sorted(
            known_schema_revisions()
            - heads
        )
        assert older
        stamp(database, older[0])

        with pytest.raises(
            DatabaseSchemaCompatibilityError
        ) as old_error:
            assert_database_schema_current(
                database
            )
        assert (
            old_error.value.code
            == "database_migration_required"
        )

        stamp(
            database,
            "ffff_unknown_revision",
        )
        with pytest.raises(
            DatabaseSchemaCompatibilityError
        ) as unknown_error:
            assert_database_schema_current(
                database
            )
        assert (
            unknown_error.value.code
            == "database_schema_unsupported"
        )
    finally:
        database.close()



def test_all_canonical_datetime_columns_use_utc_datetime(
    tmp_path: Path,
) -> None:
    # Building the application imports the complete canonical model graph.
    app = create_app(
        Settings(
            secret_key=(
                "utc-schema-guard-test-secret-key-"
                "32-bytes-minimum"
            ),
            environment="test",
            database_url=(
                f"sqlite:///{tmp_path / 'utc-schema.db'}"
            ),
            data_dir=tmp_path / "data-utc",
            cache_dir=tmp_path / "cache-utc",
        )
    )
    try:
        offenders: list[str] = []
        for table in Base.metadata.sorted_tables:
            for column in table.columns:
                if isinstance(
                    column.type,
                    DateTime,
                ) and not isinstance(
                    column.type,
                    UTCDateTime,
                ):
                    offenders.append(
                        f"{table.name}.{column.name}"
                    )

        assert offenders == [], (
            "Canonical datetime columns must use "
            f"UTCDateTime: {offenders}"
        )
    finally:
        app.state.database.close()


def test_utc_datetime_normalizes_offsets_and_rejects_naive_values() -> None:
    column_type = UTCDateTime()

    plus_eight = datetime(
        2026,
        9,
        22,
        8,
        30,
        tzinfo=timezone(timedelta(hours=8)),
    )
    normalized = column_type.process_bind_param(
        plus_eight,
        dialect=None,  # type: ignore[arg-type]
    )
    assert normalized == datetime(
        2026,
        9,
        22,
        0,
        30,
        tzinfo=UTC,
    )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        column_type.process_bind_param(
            datetime(2026, 9, 22, 0, 30),
            dialect=None,  # type: ignore[arg-type]
        )
