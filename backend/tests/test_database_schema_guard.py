from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.core.db import (
    Base,
    Database,
    DatabaseSchemaCompatibilityError,
    assert_database_schema_current,
    expected_schema_heads,
    known_schema_revisions,
)


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
