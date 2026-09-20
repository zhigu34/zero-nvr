from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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
        tables = set(inspect(engine).get_table_names())
        assert EXPECTED_FOUNDATION_TABLES <= tables
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
