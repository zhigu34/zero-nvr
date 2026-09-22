from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.core.security import SecretStore
from app.main import create_app
from app.modules.auth.models import SecretRecord
from app.modules.cameras.models import (
    Camera,
    Device,
    DeviceCredential,
    DeviceEndpoint,
)


ADMIN_PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="system-ntp-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'system-ntp.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def test_apply_camera_ntp_uses_saved_servers_and_encrypted_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    calls = []
    read_calls = []
    clock_mode = {
        "value": "NTP",
    }

    async def fake_configure(self, **kwargs):
        calls.append(kwargs)

    async def fake_clock(self, **kwargs):
        read_calls.append(kwargs)

        class Reading:
            date_time_type = (
                clock_mode["value"]
            )
            timezone = "UTC0"
            utc_datetime = datetime(
                2026,
                9,
                22,
                12,
                0,
                tzinfo=UTC,
            )
            offset_ms = 350.0
            rtt_ms = 120.0

        return Reading()

    monkeypatch.setattr(
        "app.modules.system.api.OnvifAdapter.configure_ntp",
        fake_configure,
    )
    monkeypatch.setattr(
        "app.modules.system.api.OnvifAdapter.read_system_clock",
        fake_clock,
    )

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 201
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200

        with app.state.database.session() as session:
            device = Device(
                name="Front Door Device",
                adapter_type="onvif",
                enabled=True,
                capabilities_json={},
            )
            session.add(device)
            session.flush()
            managed_camera = Camera(
                device_id=device.id,
                channel_key="front-door",
                name="Front Door Camera",
                enabled=True,
                time_sync_mode="manage_ntp",
            )
            session.add(
                managed_camera
            )
            session.flush()
            managed_camera_id = (
                managed_camera.id
            )

            monitor_device = Device(
                name="Monitor Only Device",
                adapter_type="onvif",
                enabled=True,
                capabilities_json={},
            )
            session.add(
                monitor_device
            )
            session.flush()
            session.add(
                Camera(
                    device_id=monitor_device.id,
                    channel_key="monitor-only",
                    name="Monitor Only Camera",
                    enabled=True,
                    time_sync_mode="monitor",
                )
            )

            endpoint = DeviceEndpoint(
                device_id=device.id,
                type="onvif",
                host="192.168.10.40",
                port=80,
                scheme="http",
                priority=100,
                enabled=True,
                metadata_json={},
            )
            session.add(endpoint)
            session.flush()

            encrypted = SecretStore(
                app.state.settings
            ).encrypt_json(
                {
                    "username": "onvif-admin",
                    "password": "onvif-secret",
                }
            )
            secret = SecretRecord(
                kind="onvif_credential",
                owner_type="device",
                owner_id=device.id,
                key_id=encrypted.key_id,
                encrypted_payload=encrypted.ciphertext,
                version=encrypted.version,
            )
            session.add(secret)
            session.flush()
            session.add(
                DeviceCredential(
                    device_id=device.id,
                    endpoint_id=endpoint.id,
                    kind="onvif",
                    secret_ref=secret.id,
                )
            )
            session.commit()

        saved = client.patch(
            "/api/v1/system/settings",
            json={
                "time": {
                    "recording_timezone": "UTC",
                    "managed_camera_ntp_mode": (
                        "manual"
                    ),
                    "managed_camera_ntp_servers": [
                        "pool.ntp.org",
                        "192.0.2.10",
                    ],
                }
            },
        )
        assert saved.status_code == 200

        applied = client.post(
            "/api/v1/system/settings/camera-ntp/apply"
        )
        assert applied.status_code == 200
        body = applied.json()
        assert body["mode"] == "manual"
        assert body["total_devices"] == 1
        assert body["updated"] == 1
        assert body["failed"] == 0
        assert body["results"][0]["status"] == "UPDATED"
        assert (
            body["results"][0]["verified"]
            is True
        )
        assert (
            body["results"][0][
                "date_time_type"
            ]
            == "NTP"
        )
        assert (
            body["results"][0]["offset_ms"]
            == 350
        )
        assert (
            body["results"][0]["rtt_ms"]
            == 120
        )

        assert len(calls) == 1
        assert len(read_calls) == 1
        assert calls[0]["host"] == "192.168.10.40"
        assert calls[0]["username"] == "onvif-admin"
        assert calls[0]["password"] == "onvif-secret"
        assert calls[0]["servers"] == (
            "pool.ntp.org",
            "192.0.2.10",
        )

        serialized = str(body)
        assert "onvif-secret" not in serialized
        assert "onvif-admin" not in serialized

        switched = client.patch(
            "/api/v1/system/settings",
            json={
                "time": {
                    "managed_camera_ntp_mode": (
                        "dhcp"
                    )
                }
            },
        )
        assert switched.status_code == 200
        assert switched.json()["time"] == {
            "recording_timezone": "UTC",
            "managed_camera_ntp_mode": "dhcp",
            "managed_camera_ntp_servers": [
                "pool.ntp.org",
                "192.0.2.10",
            ],
        }

        dhcp = client.post(
            "/api/v1/system/settings/camera-ntp/apply"
        )
        assert dhcp.status_code == 200
        assert dhcp.json()["mode"] == "dhcp"
        assert (
            dhcp.json()["results"][0][
                "verified"
            ]
            is True
        )
        assert calls[-1]["servers"] == ()
        assert len(calls) == 2
        assert len(read_calls) == 2

        clock_mode["value"] = "Manual"
        mismatch = client.post(
            "/api/v1/system/settings/camera-ntp/apply"
        )
        assert mismatch.status_code == 200
        mismatch_body = mismatch.json()
        assert mismatch_body["updated"] == 0
        assert mismatch_body["failed"] == 1
        assert (
            mismatch_body["results"][0][
                "status"
            ]
            == "FAILED"
        )
        assert (
            mismatch_body["results"][0][
                "verified"
            ]
            is False
        )
        assert (
            mismatch_body["results"][0][
                "error_code"
            ]
            == "camera_ntp_verify_mode_mismatch"
        )
        assert len(calls) == 3
        assert len(read_calls) == 3

        projection = client.get(
            (
                f"/api/v1/cameras/"
                f"{managed_camera_id}/clock"
            )
        )
        assert projection.status_code == 200
        current = projection.json()
        assert (
            current["sync_mode"]
            == "manage_ntp"
        )
        assert (
            current["error_code"]
            == "camera_ntp_verify_mode_mismatch"
        )
        assert (
            current["device_time_source"]
            == "Manual"
        )



def test_camera_clock_health_reports_offset_rtt_and_sanitized_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)

    class Reading:
        date_time_type = "NTP"
        timezone = "UTC0"
        utc_datetime = datetime(
            2026, 9, 20, 14, 30, 10, tzinfo=UTC
        )
        offset_ms = 1250.0
        rtt_ms = 180.0

    async def fake_clock(self, **kwargs):
        assert kwargs["username"] == "onvif-admin"
        assert kwargs["password"] == "onvif-secret"
        return Reading()

    monkeypatch.setattr(
        "app.modules.system.api.OnvifAdapter.read_system_clock",
        fake_clock,
    )

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/setup/administrator",
            json={
                "username": "admin",
                "display_name": "Administrator",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 201
        assert client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": ADMIN_PASSWORD,
            },
        ).status_code == 200

        with app.state.database.session() as session:
            device = Device(
                name="Clock Camera",
                adapter_type="onvif",
                enabled=True,
                capabilities_json={},
            )
            session.add(device)
            session.flush()
            device_id = device.id
            camera = Camera(
                device_id=device.id,
                channel_key="clock-camera",
                name="Clock Camera",
                enabled=True,
            )
            session.add(camera)
            session.flush()
            camera_id = camera.id

            endpoint = DeviceEndpoint(
                device_id=device.id,
                type="onvif",
                host="192.168.10.41",
                port=80,
                scheme="http",
                priority=100,
                enabled=True,
                metadata_json={},
            )
            session.add(endpoint)
            session.flush()
            encrypted = SecretStore(
                app.state.settings
            ).encrypt_json(
                {
                    "username": "onvif-admin",
                    "password": "onvif-secret",
                }
            )
            secret = SecretRecord(
                kind="onvif_credential",
                owner_type="device",
                owner_id=device.id,
                key_id=encrypted.key_id,
                encrypted_payload=encrypted.ciphertext,
                version=encrypted.version,
            )
            session.add(secret)
            session.flush()
            session.add(
                DeviceCredential(
                    device_id=device.id,
                    endpoint_id=endpoint.id,
                    kind="onvif",
                    secret_ref=secret.id,
                )
            )
            session.commit()

        camera_view = client.get(
            f"/api/v1/cameras/{camera_id}"
        )
        assert camera_view.status_code == 200
        assert (
            camera_view.json()["time_sync_mode"]
            == "monitor"
        )

        before = client.get(
            f"/api/v1/cameras/{camera_id}/clock"
        )
        assert before.status_code == 200
        assert before.json()["sync_mode"] == "monitor"
        assert before.json()["health"] == "unknown"
        assert before.json()["quality"] == "unknown"
        assert before.json()["measured_at"] is None

        response = client.get(
            "/api/v1/system/camera-clock-health"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "OK"
        assert body["total_devices"] == 1
        assert body["ok"] == 1
        item = body["results"][0]
        assert item["status"] == "OK"
        assert item["date_time_type"] == "NTP"
        assert item["offset_ms"] == 1250
        assert item["rtt_ms"] == 180
        assert "onvif-secret" not in str(body)
        assert "onvif-admin" not in str(body)

        projection = client.get(
            f"/api/v1/cameras/{camera_id}/clock"
        )
        assert projection.status_code == 200
        current = projection.json()
        assert current["device_id"] == str(
            device_id
        )
        assert current["health"] == "healthy"
        assert current["quality"] == "good"
        assert current["offset_ms"] == 1250
        assert current["rtt_ms"] == 180
        assert current["uncertainty_ms"] == 90
        assert current["device_timezone"] == "UTC0"
        assert current["device_time_source"] == "NTP"
        assert current["measured_at"] is not None

        assert (
            "camera_clock_statuses"
            not in Base.metadata.tables
        )

        ignored = client.patch(
            f"/api/v1/cameras/{camera_id}",
            json={
                "time_sync_mode": "ignore",
            },
        )
        assert ignored.status_code == 200
        assert (
            ignored.json()["time_sync_mode"]
            == "ignore"
        )

        skipped = client.get(
            "/api/v1/system/camera-clock-health"
        )
        assert skipped.status_code == 200
        assert skipped.json()["status"] == "DISABLED"
        assert skipped.json()["total_devices"] == 0

        ignored_projection = client.get(
            f"/api/v1/cameras/{camera_id}/clock"
        )
        assert ignored_projection.status_code == 200
        ignored_current = (
            ignored_projection.json()
        )
        assert (
            ignored_current["sync_mode"]
            == "ignore"
        )
        assert (
            ignored_current["health"]
            == "unknown"
        )
        assert (
            ignored_current["offset_ms"]
            is None
        )
