from __future__ import annotations

import uuid
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import SecretRecord
from app.modules.recordings.models import RecordingPolicy
from app.modules.storage.models import StorageTarget


ADMIN_PASSWORD = "correct-horse-battery-staple"
VIEWER_PASSWORD = "viewer-correct-horse-battery"
RCLONE_SECRET = """[archive]
type = webdav
url = https://example.invalid/dav
user = archive
pass = super-secret-rclone-password
"""


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="storage-api-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'storage.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=tmp_path / "recordings",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
        session_cookie_secure=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def setup_admin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": ADMIN_PASSWORD,
        },
    )
    assert login.status_code == 200


def test_storage_target_secret_is_encrypted_and_never_returned(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)

        local_root = tmp_path / "recordings"
        local_root.mkdir(parents=True, exist_ok=True)
        local = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Local Recording",
                "enabled": True,
                "config": {
                    "path": str(local_root),
                    "default_recording": True,
                },
            },
        )
        assert local.status_code == 201
        assert local.json()["credentials_configured"] is False

        remote = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "rclone",
                "role": "archive",
                "name": "Cloud Archive",
                "enabled": True,
                "config": {
                    "remote": "archive",
                    "base_path": "zero-nvr/archive",
                },
                "rclone_config": RCLONE_SECRET,
            },
        )
        assert remote.status_code == 201
        remote_body = remote.json()
        assert remote_body["credentials_configured"] is True
        assert remote_body["config"] == {
            "remote": "archive",
            "base_path": "zero-nvr/archive",
        }
        assert "super-secret-rclone-password" not in remote.text
        assert "example.invalid" not in json.dumps(
            remote_body["config"]
        )

        listed = client.get("/api/v1/storage/targets")
        assert listed.status_code == 200
        serialized = listed.text
        assert "super-secret-rclone-password" not in serialized
        assert "pass =" not in serialized

        local_test = client.post(
            f"/api/v1/storage/targets/{local.json()['id']}/test"
        )
        assert local_test.status_code == 200
        assert local_test.json()["detail"] == "read_write_ok"
        assert local_test.json()["free_bytes"] > 0

        conflict = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Another Default",
                "enabled": True,
                "config": {
                    "path": str(tmp_path / "other"),
                    "default_recording": True,
                },
            },
        )
        assert conflict.status_code == 409
        assert (
            conflict.json()["error"]["code"]
            == "default_recording_target_conflict"
        )

        with app.state.database.session() as session:
            target = session.get(
                StorageTarget,
                uuid.UUID(remote_body["id"]),
            )
            assert target is not None
            assert target.credential_secret_ref is not None
            secret = session.get(
                SecretRecord,
                target.credential_secret_ref,
            )
            assert secret is not None
            assert b"super-secret-rclone-password" not in (
                secret.encrypted_payload
            )
            assert b"example.invalid" not in secret.encrypted_payload

            audit_json = json.dumps(
                [
                    {
                        "before": row.before_json,
                        "after": row.after_json,
                    }
                    for row in session.scalars(
                        select(AuditEvent).where(
                            AuditEvent.resource_type
                            == "storage_target"
                        )
                    )
                ]
            )
            assert "super-secret-rclone-password" not in audit_json
            assert "pass =" not in audit_json


def test_storage_target_delete_is_blocked_while_policy_references_it(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        root = tmp_path / "recordings"
        root.mkdir(parents=True, exist_ok=True)
        created = client.post(
            "/api/v1/storage/targets",
            json={
                "type": "local",
                "role": "recording",
                "name": "Local Recording",
                "config": {
                    "path": str(root),
                    "default_recording": True,
                },
            },
        )
        assert created.status_code == 201

        # A direct policy reference is enough to protect target identity.
        with app.state.database.session() as session:
            from app.modules.cameras.service import CameraService

            camera = CameraService(
                app.state.settings
            ).create_manual_rtsp_camera(
                session,
                name="Front Door",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url="rtsp://camera.local/main",
                secondary_name=None,
                secondary_url=None,
            )
            session.add(
                RecordingPolicy(
                    camera_id=camera.id,
                    baseline_mode="continuous",
                    storage_target_id=uuid.UUID(created.json()["id"]),
                    enabled=True,
                )
            )
            session.commit()

        deleted = client.delete(
            f"/api/v1/storage/targets/{created.json()['id']}"
        )
        assert deleted.status_code == 409
        assert (
            deleted.json()["error"]["code"]
            == "storage_target_in_use"
        )
