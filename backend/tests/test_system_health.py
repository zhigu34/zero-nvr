from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.modules.storage.capacity as capacity_module
import app.modules.system.health as health_module
from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.storage.models import StorageTarget
from app.modules.system.health import (
    HealthComponent,
    SystemHealthService,
    write_worker_heartbeat,
)


PASSWORD = "correct-horse-battery-staple"


class FakeZlm:
    def __init__(self, _settings, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def version(self):
        return {
            "version": "1.0-test",
            "commit": None,
        }


def make_app(tmp_path: Path):
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    settings = Settings(
        secret_key="system-health-test-secret-key-32-bytes",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'health.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=recordings,
        session_cookie_secure=False,
        zlm_api_secret=SecretStr("zlm-secret-value"),
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def setup_admin(client: TestClient) -> None:
    created = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": PASSWORD,
        },
    )
    assert created.status_code == 201
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": PASSWORD},
    ).status_code == 200


def test_product_health_aggregates_runtime_without_db_health_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    monkeypatch.setattr(
        health_module,
        "ZlmAdapter",
        FakeZlm,
    )
    monkeypatch.setattr(
        health_module,
        "read_host_clock_kernel_state",
        lambda: health_module.HostClockKernelState(
            synchronized=True,
            time_state=0,
            status_flags=0,
            estimated_offset_ms=0.125,
            estimated_error_ms=0.25,
            max_error_ms=1.5,
            tai_offset_seconds=37,
        ),
    )

    with app.state.database.session() as session:
        session.add(
            StorageTarget(
                name="Local Recording",
                type="local",
                role="recording",
                enabled=True,
                config_json={
                    "path": str(
                        app.state.settings.recordings_dir
                    )
                },
            )
        )
        session.commit()

    write_worker_heartbeat(
        app.state.settings
    )

    with TestClient(app) as client:
        setup_admin(client)
        response = client.get(
            "/api/v1/system/health"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "DEGRADED"
        assert (
            body["components"]["recording_reconciliation"]["status"]
            == "DEGRADED"
        )
        assert (
            body["components"]["recording_reconciliation"]["message"]
            == "recording_reconciliation_pending"
        )
        assert body["components"]["database"]["status"] == "OK"
        database_details = body["components"]["database"]["details"]
        assert database_details["backend"] == "sqlite"
        assert database_details["journal_mode"] == "wal"
        assert database_details["busy_timeout_ms"] == 5000
        assert database_details["wal_autocheckpoint_pages"] == 1000
        assert database_details["write_pressure"] == "normal"
        assert body["components"]["worker"]["status"] == "OK"
        assert body["components"]["zlmediakit"]["status"] == "OK"
        assert body["components"]["storage"]["status"] == "OK"
        storage_details = body["components"]["storage"]["details"]
        assert storage_details["targets"] == 1
        assert storage_details["unavailable_targets"] == 0
        assert len(storage_details["target_details"]) == 1
        assert (
            storage_details["target_details"][0]["level"]
            == "normal"
        )
        assert body["components"]["frigate"]["status"] == "DISABLED"
        assert body["components"]["archive"]["status"] == "DISABLED"
        host_clock = body["components"]["host_clock"]
        assert host_clock["status"] == "OK"
        assert (
            host_clock["details"]["canonical_timezone"]
            == "UTC"
        )
        assert (
            host_clock["details"]["sync_state"]
            == "synchronized"
        )
        assert (
            host_clock["details"]["estimated_offset_ms"]
            == 0.125
        )

        client.post("/api/v1/auth/logout")
        denied = client.get(
            "/api/v1/system/health"
        )
        assert denied.status_code == 401

        assert client.get("/health").status_code == 200



def test_database_health_degrades_on_sqlite_write_pressure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    database = app.state.database
    try:
        monkeypatch.setattr(
            database,
            "sqlite_runtime_health",
            lambda: SimpleNamespace(
                journal_mode="wal",
                busy_timeout_ms=5000,
                wal_autocheckpoint_pages=1000,
                page_size_bytes=4096,
                wal_pages=8000,
                checkpointed_pages=5000,
                backlog_pages=3000,
                wal_bytes=32 * 1024 * 1024,
                checkpoint_busy=False,
                write_pressure="high",
            ),
        )
        component = SystemHealthService(
            app.state.settings,
            database,
        )._database()
        assert component.status == "DEGRADED"
        assert (
            component.message
            == "sqlite_write_pressure_high"
        )
        assert (
            component.details["write_pressure"]
            == "high"
        )
        assert component.details["backlog_pages"] == 3000
    finally:
        database.close()


def test_health_surfaces_recording_reconciliation_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from datetime import UTC, datetime

    from app.modules.system.models import SystemSetting

    app = make_app(tmp_path)
    settings = app.state.settings
    database = app.state.database
    try:
        monkeypatch.setattr(
            SystemHealthService,
            "_zlm",
            lambda self: HealthComponent(
                status="OK"
            ),
        )
        monkeypatch.setattr(
            SystemHealthService,
            "_worker",
            lambda self: HealthComponent(
                status="OK"
            ),
        )
        monkeypatch.setattr(
            SystemHealthService,
            "_local_storage",
            staticmethod(
                lambda targets: HealthComponent(
                    status="OK"
                )
            ),
        )

        with database.session() as session:
            session.add(
                SystemSetting(
                    namespace=(
                        "recording.reconciliation"
                    ),
                    value_json={
                        "last_completed_at": (
                            datetime.now(UTC)
                            .isoformat()
                        ),
                        "last_full_at": None,
                        "last_result": {
                            "full": False,
                            "scanned_files": 2,
                            "recovered": 1,
                            "relinked": 0,
                            "missing": 0,
                            "ambiguous": 0,
                            "errors": 0,
                            "skipped_unsettled": 0,
                        },
                    },
                )
            )
            session.commit()

        health = SystemHealthService(
            settings,
            database,
        ).collect()
        component = health.components[
            "recording_reconciliation"
        ]
        assert component.status == "OK"
        assert (
            component.details["recovered"]
            == 1
        )

        with database.session() as session:
            state = session.get(
                SystemSetting,
                "recording.reconciliation",
            )
            assert state is not None
            state.value_json = {
                **state.value_json,
                "last_result": {
                    **state.value_json[
                        "last_result"
                    ],
                    "ambiguous": 1,
                },
            }
            session.commit()

        degraded = SystemHealthService(
            settings,
            database,
        ).collect()
        component = degraded.components[
            "recording_reconciliation"
        ]
        assert component.status == "DEGRADED"
        assert (
            component.message
            == "recording_media_ambiguous"
        )
    finally:
        database.close()



def test_storage_health_surfaces_capacity_watermarks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    root = app.state.settings.recordings_dir

    with app.state.database.session() as session:
        target = StorageTarget(
            name="Local Recording",
            type="local",
            role="recording",
            enabled=True,
            config_json={
                "path": str(root),
                "warning_used_percent": 80,
                "high_used_percent": 85,
                "critical_used_percent": 95,
            },
        )
        session.add(target)
        session.commit()
        session.refresh(target)
        session.expunge(target)

    def fake_statvfs(_path):
        return SimpleNamespace(
            f_blocks=100,
            f_bavail=12,
            f_frsize=1024,
        )

    monkeypatch.setattr(
        capacity_module.os,
        "statvfs",
        fake_statvfs,
    )

    component = SystemHealthService._local_storage(
        [target]
    )
    assert component.status == "DEGRADED"
    assert (
        component.message
        == "recording_storage_capacity_high"
    )
    assert component.details["high_targets"] == 1
    detail = component.details["target_details"][0]
    assert detail["level"] == "high"
    assert detail["used_percent"] == 88.0
    assert detail["warning_percent"] == 80
    assert detail["high_percent"] == 85
    assert detail["critical_percent"] == 95

    def critical_statvfs(_path):
        return SimpleNamespace(
            f_blocks=100,
            f_bavail=4,
            f_frsize=1024,
        )

    monkeypatch.setattr(
        capacity_module.os,
        "statvfs",
        critical_statvfs,
    )
    critical = SystemHealthService._local_storage(
        [target]
    )
    assert critical.status == "ERROR"
    assert (
        critical.message
        == "recording_storage_capacity_critical"
    )
    assert (
        critical.details["critical_targets"]
        == 1
    )


def test_storage_health_marks_unavailable_target_error(
    tmp_path: Path,
) -> None:
    target = StorageTarget(
        name="Missing Recording",
        type="local",
        role="recording",
        enabled=True,
        config_json={
            "path": str(
                tmp_path / "missing"
            ),
        },
    )
    component = SystemHealthService._local_storage(
        [target]
    )
    assert component.status == "ERROR"
    assert (
        component.message
        == "recording_storage_unavailable"
    )
    assert (
        component.details["unavailable_targets"]
        == 1
    )
    detail = component.details["target_details"][0]
    assert detail["level"] == "unavailable"

def test_liveness_stays_up_when_readiness_database_probe_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        assert client.get("/health").json() == {
            "status": "ok"
        }
        assert client.get("/ready").json() == {
            "status": "ok"
        }

        def fail_ping() -> None:
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(
            app.state.database,
            "ping",
            fail_ping,
        )

        liveness = client.get("/health")
        assert liveness.status_code == 200
        assert liveness.json() == {
            "status": "ok"
        }

        readiness = client.get("/ready")
        assert readiness.status_code == 503
        assert readiness.json() == {
            "status": "unavailable"
        }

def test_host_clock_health_reports_kernel_sync_state(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "read_host_clock_kernel_state",
        lambda: health_module.HostClockKernelState(
            synchronized=False,
            time_state=5,
            status_flags=0x40,
            estimated_offset_ms=-1250.5,
            estimated_error_ms=3500.0,
            max_error_ms=5000.0,
            tai_offset_seconds=37,
        ),
    )

    component = SystemHealthService._host_clock()
    assert component.status == "DEGRADED"
    assert (
        component.message
        == "host_clock_unsynchronized"
    )
    assert (
        component.details["canonical_timezone"]
        == "UTC"
    )
    assert (
        component.details["sync_state"]
        == "unsynchronized"
    )
    assert (
        component.details["estimated_offset_ms"]
        == -1250.5
    )
    assert (
        component.details["source"]
        == "linux_adjtimex"
    )


def test_host_clock_health_is_optional_when_probe_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "read_host_clock_kernel_state",
        lambda: None,
    )

    component = SystemHealthService._host_clock()
    assert component.status == "DISABLED"
    assert (
        component.message
        == "host_clock_sync_probe_unavailable"
    )
    assert (
        component.details["canonical_timezone"]
        == "UTC"
    )

