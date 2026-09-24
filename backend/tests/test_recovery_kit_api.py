from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.db import Base
from app.main import create_app
from app.modules.backups.recovery_kit import (
    RecoveryKitService,
)


PASSWORD = "correct-horse-battery-staple"
KIT_PASSPHRASE = "recovery-kit-passphrase-strong"
RESTIC_PASSWORD = "restic-secret-password"


def make_app(tmp_path: Path):
    settings = Settings(
        secret_key="s" * 40,
        secret_key_previous=[SecretStr("p" * 40)],
        app_version="1.2.3",
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'recovery.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=tmp_path / "recordings",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
        session_cookie_secure=False,
        zlm_api_secret=SecretStr("a" * 40),
        zlm_hook_secret=SecretStr("h" * 40),
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def setup_admin(client: TestClient) -> None:
    assert client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": PASSWORD,
        },
    ).status_code == 201
    assert client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": PASSWORD,
        },
    ).status_code == 200


def create_policy(client: TestClient) -> str:
    response = client.post(
        "/api/v1/backups/policies",
        json={
            "name": "Recovery",
            "enabled": True,
            "repository": (
                "s3:s3.example.test/zero-nvr"
            ),
            "credentials": {
                "password": RESTIC_PASSWORD,
                "environment": {
                    "AWS_ACCESS_KEY_ID": "access-key",
                    "AWS_SECRET_ACCESS_KEY": "secret-key",
                },
            },
            "initialize_if_missing": False,
            "database_backend": "sqlite",
            "schedule": {},
            "retention": {"keep_last": 7},
            "verify_after_backup": True,
            "repository_check_schedule": {},
            "include_deployment_config": True,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_recovery_kit_download_is_encrypted_and_tracks_staleness(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    with TestClient(app) as client:
        setup_admin(client)
        policy_id = create_policy(client)

        before = client.get(
            "/api/v1/backups/recovery-kit/status",
            params={"policy_id": policy_id},
        )
        assert before.status_code == 200
        assert (
            before.json()["status"]
            == "never_generated"
        )

        response = client.post(
            "/api/v1/backups/recovery-kit",
            json={
                "policy_id": policy_id,
                "passphrase": KIT_PASSPHRASE,
            },
        )
        assert response.status_code == 200
        assert (
            response.headers["cache-control"]
            == "no-store"
        )
        assert ".znrk" in response.headers[
            "content-disposition"
        ]

        raw = response.content
        assert b"restic-secret-password" not in raw
        assert b"secret-key" not in raw
        assert b'"s" * 40' not in raw

        envelope = json.loads(raw)
        assert (
            envelope["format"]
            == "zero-nvr.recovery-kit.encrypted"
        )
        payload = RecoveryKitService.decrypt(
            raw,
            passphrase=KIT_PASSPHRASE,
        )
        files = payload["files"]
        assert RESTIC_PASSWORD in files["recovery.env"]
        assert "ZERO_NVR_SECRET_KEY=" in files[
            "zero-nvr.env"
        ]
        assert ("s" * 40) in files["zero-nvr.env"]
        assert ("p" * 40) in files["zero-nvr.env"]

        current = client.get(
            "/api/v1/backups/recovery-kit/status",
            params={"policy_id": policy_id},
        )
        assert current.status_code == 200
        assert current.json()["status"] == "current"

        updated = client.patch(
            f"/api/v1/backups/policies/{policy_id}",
            json={
                "retention": {
                    "keep_last": 5,
                }
            },
        )
        assert updated.status_code == 200

        stale = client.get(
            "/api/v1/backups/recovery-kit/status",
            params={"policy_id": policy_id},
        )
        assert stale.status_code == 200
        assert stale.json()["status"] == "stale"


def test_recovery_kit_rejects_short_passphrase(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    with TestClient(app) as client:
        setup_admin(client)
        policy_id = create_policy(client)
        response = client.post(
            "/api/v1/backups/recovery-kit",
            json={
                "policy_id": policy_id,
                "passphrase": "too-short",
            },
        )
        assert response.status_code == 422



def test_recovery_kit_extract_writes_only_expected_files(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    with TestClient(app) as client:
        setup_admin(client)
        policy_id = create_policy(client)
        response = client.post(
            "/api/v1/backups/recovery-kit",
            json={
                "policy_id": policy_id,
                "passphrase": KIT_PASSPHRASE,
            },
        )
        assert response.status_code == 200

    output = tmp_path / "extracted"
    written = RecoveryKitService.extract(
        response.content,
        passphrase=KIT_PASSPHRASE,
        destination=output,
    )
    assert {
        path.name
        for path in written
    } == {
        "zero-nvr.env",
        "recovery.env",
        "README.txt",
    }
    assert (
        output / "zero-nvr.env"
    ).stat().st_mode & 0o777 == 0o600
    assert (
        output / "recovery.env"
    ).stat().st_mode & 0o777 == 0o600

    try:
        RecoveryKitService.extract(
            response.content,
            passphrase=KIT_PASSPHRASE,
            destination=output,
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError(
            "RecoveryKit extraction overwrote files"
        )
