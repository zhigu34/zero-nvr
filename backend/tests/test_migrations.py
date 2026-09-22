from __future__ import annotations

import os
from pathlib import Path

import pytest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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
