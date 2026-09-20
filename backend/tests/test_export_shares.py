from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.cameras.service import CameraService
from app.modules.exports.models import ExportJob, ExportShareToken


PASSWORD = "correct-horse-battery-staple"
SHARE_PASSWORD = "very-secure-share-password"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="export-share-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'share.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
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
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": PASSWORD},
    )
    assert login.status_code == 200


def seed_completed_export(app) -> uuid.UUID:
    with app.state.database.session() as session:
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
        output = (
            app.state.settings.cache_dir
            / "exports"
            / "shared.mp4"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"shared-video")

        job = ExportJob(
            camera_id=camera.id,
            requested_by=None,
            requested_start_at=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
            requested_end_at=datetime(2026, 9, 20, 0, 1, tzinfo=UTC),
            requested_duration_ms=60_000,
            format="mp4",
            codec_mode="copy",
            gap_policy="skip",
            state="COMPLETED",
            output_path=str(output),
            size_bytes=output.stat().st_size,
            actual_duration_ms=60_000,
            selected_segment_count=1,
            metadata_json={},
            expires_at=datetime(2026, 9, 21, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 9, 20, 0, 2, tzinfo=UTC),
        )
        session.add(job)
        session.commit()
        return job.id


def basic(password: str) -> str:
    raw = base64.b64encode(
        f"user:{password}".encode("utf-8")
    ).decode("ascii")
    return f"Basic {raw}"


def test_password_share_token_is_hash_only_and_enforces_limit(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        export_id = seed_completed_export(app)

        created = client.post(
            f"/api/v1/exports/{export_id}/shares",
            json={
                "password": SHARE_PASSWORD,
                "expires_in_hours": 12,
                "max_downloads": 1,
            },
        )
        assert created.status_code == 201
        body = created.json()
        token = body["token"]
        share_id = uuid.UUID(body["id"])
        assert token in body["download_path"]
        assert body["password_protected"] is True
        assert body["download_count"] == 0

        listed = client.get(
            f"/api/v1/exports/{export_id}/shares"
        )
        assert listed.status_code == 200
        assert "token" not in listed.json()[0]

        with app.state.database.session() as session:
            share = session.get(
                ExportShareToken,
                share_id,
            )
            assert share is not None
            assert share.token_hash == hashlib.sha256(
                token.encode("utf-8")
            ).hexdigest()
            assert token not in share.token_hash
            assert share.password_hash is not None
            assert SHARE_PASSWORD not in share.password_hash

        missing_password = client.get(
            f"/api/v1/shared/exports/{token}/download"
        )
        assert missing_password.status_code == 401

        with app.state.database.session() as session:
            share = session.get(
                ExportShareToken,
                share_id,
            )
            assert share is not None
            assert share.download_count == 0

        wrong = client.get(
            f"/api/v1/shared/exports/{token}/download",
            headers={
                "Authorization": basic("wrong-password-value")
            },
        )
        assert wrong.status_code == 401

        success = client.get(
            f"/api/v1/shared/exports/{token}/download",
            headers={
                "Authorization": basic(SHARE_PASSWORD)
            },
        )
        assert success.status_code == 200
        assert success.content == b"shared-video"

        with app.state.database.session() as session:
            share = session.get(
                ExportShareToken,
                share_id,
            )
            assert share is not None
            assert share.download_count == 1
            assert share.last_download_at is not None

        limited = client.get(
            f"/api/v1/shared/exports/{token}/download",
            headers={
                "Authorization": basic(SHARE_PASSWORD)
            },
        )
        assert limited.status_code == 410
        assert (
            limited.json()["error"]["code"]
            == "export_share_download_limit_reached"
        )


def test_missing_file_does_not_consume_share_quota_and_revoke_blocks(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        export_id = seed_completed_export(app)

        created = client.post(
            f"/api/v1/exports/{export_id}/shares",
            json={
                "expires_in_hours": 12,
                "max_downloads": 2,
            },
        )
        token = created.json()["token"]
        share_id = uuid.UUID(created.json()["id"])

        with app.state.database.session() as session:
            job = session.get(ExportJob, export_id)
            assert job is not None
            Path(job.output_path).unlink()

        missing = client.get(
            f"/api/v1/shared/exports/{token}/download"
        )
        assert missing.status_code == 409

        with app.state.database.session() as session:
            share = session.get(
                ExportShareToken,
                share_id,
            )
            assert share is not None
            assert share.download_count == 0

        revoked = client.delete(
            f"/api/v1/exports/{export_id}/shares/{share_id}"
        )
        assert revoked.status_code == 204

        blocked = client.get(
            f"/api/v1/shared/exports/{token}/download"
        )
        assert blocked.status_code == 410
        assert (
            blocked.json()["error"]["code"]
            == "export_share_expired"
        )
