from __future__ import annotations

import os
from pathlib import Path

import pytest

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


from app import cli
from app.core.config import Settings
from app.core.db import (
    Database,
    MIGRATION_POLICIES,
    MigrationClass,
    MigrationPolicy,
    SQLiteMigrationStrategy,
    build_migration_plan,
    known_schema_revisions,
)


EXPECTED_SECRET_RECORD_COLUMNS = {
    "id",
    "kind",
    "owner_type",
    "owner_id",
    "key_id",
    "encrypted_payload",
    "version",
    "created_at",
    "updated_at",
}


EXPECTED_FOUNDATION_TABLES = {
    "alembic_version",
    "users",
    "roles",
    "role_permissions",
    "user_roles",
    "user_sessions",
    "password_reset_tokens",
    "personal_api_tokens",
    "external_identities",
    "secret_records",
    "system_settings",
    "audit_events",
    "devices",
    "device_endpoints",
    "device_credentials",
    "discovery_sessions",
    "discovery_candidates",
    "cameras",
    "camera_stream_profiles",
    "camera_stream_bindings",
    "camera_groups",
    "camera_group_members",
    "principal_camera_scopes",
    "principal_camera_scope_entries",
    "storage_targets",
    "retention_policies",
    "recording_policies",
    "recording_protections",
    "recording_triggers",
    "recording_segments",
    "recording_locations",
    "events",
    "alert_policies",
    "alerts",
    "notification_targets",
    "notification_deliveries",
    "exports",
    "export_share_tokens",
    "backup_policies",
    "backup_sets",
}


def alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_alembic_upgrade_head_sqlite(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "migrations.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("ZERO_NVR_DATABASE_URL", database_url)

    config = alembic_config(database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_FOUNDATION_TABLES <= tables
        secret_columns = {
            item["name"]
            for item in inspector.get_columns(
                "secret_records"
            )
        }
        assert (
            EXPECTED_SECRET_RECORD_COLUMNS
            <= secret_columns
        )
        notification_columns = {
            item["name"]: item
            for item in inspector.get_columns(
                "notification_targets"
            )
        }
        assert (
            notification_columns["secret_ref"][
                "nullable"
            ]
            is True
        )
        user_columns = {
            item["name"]
            for item in inspector.get_columns("users")
        }
        assert "email_verified_at" in user_columns
        camera_columns = {
            item["name"]: item
            for item in inspector.get_columns(
                "cameras"
            )
        }
        assert (
            camera_columns["time_sync_mode"][
                "nullable"
            ]
            is False
        )
        assert (
            camera_columns["config_revision"][
                "nullable"
            ]
            is False
        )
        assert (
            camera_columns["maintenance"][
                "nullable"
            ]
            is False
        )
        camera_checks = {
            item.get("name"): (
                item.get("sqltext") or ""
            )
            for item in inspector.get_check_constraints(
                "cameras"
            )
        }
        assert any(
            "manage_ntp" in sqltext
            and "monitor" in sqltext
            and "ignore" in sqltext
            for sqltext in camera_checks.values()
        )
        assert any(
            "config_revision" in sqltext
            and ">= 1" in sqltext
            for sqltext in camera_checks.values()
        )
        target_checks = {
            item.get("name"): (
                item.get("sqltext") or ""
            )
            for item in inspector.get_check_constraints(
                "notification_targets"
            )
        }
        assert any(
            "smtp" in sqltext
            for sqltext in target_checks.values()
        )
    finally:
        engine.dispose()


def test_camera_time_sync_migration_backfills_unsupported_cameras(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "camera-time-mode.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv(
        "ZERO_NVR_DATABASE_URL",
        database_url,
    )

    config = alembic_config(database_url)
    command.upgrade(
        config,
        "0014_notification_smtp",
    )

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                INSERT INTO devices (
                    id, name, adapter_type, enabled,
                    capabilities, created_at, updated_at
                ) VALUES
                    (
                        '11111111111111111111111111111111',
                        'ONVIF Device', 'onvif', 1, '{}',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    ),
                    (
                        '22222222222222222222222222222222',
                        'RTSP Device', 'manual_rtsp', 1, '{}',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO cameras (
                    id, device_id, channel_key, name,
                    enabled, retired_at, location,
                    storage_label, created_at, updated_at
                ) VALUES
                    (
                        '33333333333333333333333333333333',
                        '11111111111111111111111111111111',
                        'onvif-0', 'ONVIF Camera', 1,
                        NULL, NULL, NULL,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    ),
                    (
                        '44444444444444444444444444444444',
                        '22222222222222222222222222222222',
                        'manual-0', 'RTSP Camera', 1,
                        NULL, NULL, NULL,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                """
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = dict(
                connection.exec_driver_sql(
                    """
                    SELECT name, time_sync_mode
                    FROM cameras
                    ORDER BY name
                    """
                ).all()
            )
    finally:
        engine.dispose()

    assert rows == {
        "ONVIF Camera": "monitor",
        "RTSP Camera": "ignore",
    }


@pytest.mark.skipif(
    not os.getenv("ZERO_NVR_TEST_POSTGRES_URL"),
    reason="PostgreSQL CI service is unavailable",
)
def test_alembic_upgrade_head_postgresql(monkeypatch) -> None:
    database_url = os.environ["ZERO_NVR_TEST_POSTGRES_URL"]
    monkeypatch.setenv("ZERO_NVR_DATABASE_URL", database_url)

    config = alembic_config(database_url)
    command.upgrade(config, "head")

    runtime_url = database_url
    if runtime_url.startswith("postgresql://"):
        runtime_url = (
            "postgresql+psycopg://"
            + runtime_url.removeprefix("postgresql://")
        )
    elif runtime_url.startswith("postgres://"):
        runtime_url = (
            "postgresql+psycopg://"
            + runtime_url.removeprefix("postgres://")
        )

    engine = create_engine(runtime_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_FOUNDATION_TABLES <= tables
        secret_columns = {
            item["name"]
            for item in inspector.get_columns(
                "secret_records"
            )
        }
        assert (
            EXPECTED_SECRET_RECORD_COLUMNS
            <= secret_columns
        )
        notification_columns = {
            item["name"]: item
            for item in inspector.get_columns(
                "notification_targets"
            )
        }
        assert (
            notification_columns["secret_ref"][
                "nullable"
            ]
            is True
        )
        user_columns = {
            item["name"]
            for item in inspector.get_columns("users")
        }
        assert "email_verified_at" in user_columns
        camera_columns = {
            item["name"]: item
            for item in inspector.get_columns(
                "cameras"
            )
        }
        assert (
            camera_columns["time_sync_mode"][
                "nullable"
            ]
            is False
        )
        assert (
            camera_columns["config_revision"][
                "nullable"
            ]
            is False
        )
        assert (
            camera_columns["maintenance"][
                "nullable"
            ]
            is False
        )
        camera_checks = {
            item.get("name"): (
                item.get("sqltext") or ""
            )
            for item in inspector.get_check_constraints(
                "cameras"
            )
        }
        assert any(
            "manage_ntp" in sqltext
            and "monitor" in sqltext
            and "ignore" in sqltext
            for sqltext in camera_checks.values()
        )
        assert any(
            "config_revision" in sqltext
            and ">= 1" in sqltext
            for sqltext in camera_checks.values()
        )
        target_checks = {
            item.get("name"): (
                item.get("sqltext") or ""
            )
            for item in inspector.get_check_constraints(
                "notification_targets"
            )
        }
        assert any(
            "smtp" in sqltext
            for sqltext in target_checks.values()
        )
    finally:
        engine.dispose()


def test_alembic_downgrade_base_sqlite(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "downgrade.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("ZERO_NVR_DATABASE_URL", database_url)

    config = alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "users" not in tables
    assert "secret_records" not in tables
    assert "system_settings" not in tables
    assert "audit_events" not in tables
    assert "devices" not in tables
    assert "cameras" not in tables
    assert "principal_camera_scopes" not in tables
    assert "storage_targets" not in tables
    assert "retention_policies" not in tables
    assert "recording_protections" not in tables
    assert "recording_segments" not in tables
    assert "recording_locations" not in tables
    assert "events" not in tables
    assert "alert_policies" not in tables
    assert "alerts" not in tables
    assert "notification_targets" not in tables
    assert "notification_deliveries" not in tables
    assert "exports" not in tables
    assert "export_share_tokens" not in tables
    assert "backup_policies" not in tables
    assert "backup_sets" not in tables



def test_every_alembic_revision_has_migration_policy() -> None:
    assert {
        item.revision
        for item in MIGRATION_POLICIES
    } == known_schema_revisions()


def test_migration_policy_order_matches_alembic_lineage() -> None:
    config = alembic_config("sqlite://")
    script = ScriptDirectory.from_config(
        config
    )
    lineage = [
        item.revision
        for item in reversed(
            list(script.walk_revisions())
        )
    ]
    assert [
        item.revision
        for item in MIGRATION_POLICIES
    ] == lineage


def test_sqlite_migration_strategy_matches_revision_implementation() -> None:
    config = alembic_config("sqlite://")
    script = ScriptDirectory.from_config(
        config
    )

    for policy in MIGRATION_POLICIES:
        revision = script.get_revision(
            policy.revision
        )
        assert revision is not None
        source = Path(
            revision.path
        ).read_text(encoding="utf-8")

        has_batch = (
            "op.batch_alter_table" in source
        )
        if (
            policy.sqlite_strategy
            is SQLiteMigrationStrategy.BATCH
        ):
            assert has_batch, policy.revision
        elif has_batch:
            raise AssertionError(
                f"{policy.revision} uses Alembic batch "
                "but registry does not classify it as batch"
            )

        if (
            policy.sqlite_strategy
            is SQLiteMigrationStrategy.REBUILD
        ):
            assert "op.drop_table" in source
            assert "op.rename_table" in source


def test_migration_policy_classifies_transform_and_batch_paths() -> None:
    policies = {
        item.revision: item
        for item in MIGRATION_POLICIES
    }
    assert (
        policies[
            "0010_notification_delivery"
        ].migration_class
        is MigrationClass.B
    )
    assert (
        policies[
            "0010_notification_delivery"
        ].sqlite_strategy
        is SQLiteMigrationStrategy.REBUILD
    )
    assert (
        policies[
            "0015_camera_time_sync_mode"
        ].migration_class
        is MigrationClass.B
    )

    for revision in (
        "0012_notification_secret",
        "0013_user_email_verified",
        "0014_notification_smtp",
        "0015_camera_time_sync_mode",
        "0016_camera_config_revision",
        "0017_camera_maintenance",
    ):
        assert (
            policies[revision].sqlite_strategy
            is SQLiteMigrationStrategy.BATCH
        )


def test_class_c_requires_verified_backup_and_maintenance() -> None:
    policy = MigrationPolicy(
        revision="future_destructive",
        migration_class=MigrationClass.C,
        sqlite_strategy=(
            SQLiteMigrationStrategy.REBUILD
        ),
        rationale="test destructive migration",
    )
    assert policy.requires_verified_backup
    assert policy.requires_maintenance


def test_pending_plan_requires_checkpoint_for_sqlite_rebuild() -> None:
    plan = build_migration_plan(
        frozenset(
            {"0009_camera_retirement"}
        )
    )
    assert plan.highest_class is MigrationClass.B
    assert plan.requires_sqlite_checkpoint
    assert not plan.requires_verified_backup
    assert (
        plan.pending[0].revision
        == "0010_notification_delivery"
    )


def test_sqlite_migration_verify_checks_integrity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "verified-migration.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv(
        "ZERO_NVR_DATABASE_URL",
        database_url,
    )

    config = alembic_config(database_url)
    command.upgrade(config, "head")

    database = Database(
        Settings(
            secret_key=(
                "migration-verify-test-secret-key-"
                "32-bytes-minimum"
            ),
            environment="test",
            database_url=database_url,
            data_dir=tmp_path / "data",
            cache_dir=tmp_path / "cache",
            prebuffer_require_tmpfs=False,
        )
    )
    database.initialize_runtime()
    try:
        result = cli._verify_migration_result(
            database
        )
        assert result["schema_current"] is True
        assert result["sqlite_foreign_keys"] == "ok"
        assert result["sqlite_integrity"] == "ok"
        assert result["sqlite_temporary_tables"] == []

        with database.engine.connect() as connection:
            leftovers = list(
                connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE name LIKE "
                        "'_alembic_tmp_%'"
                    )
                ).scalars()
            )
        assert leftovers == []
    finally:
        database.close()
