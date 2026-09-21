from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from app.core.config import Settings
from app.modules.cameras.turn import (
    TurnCredentialService,
)


def make_settings(**overrides) -> Settings:
    values = {
        "secret_key": (
            "turn-test-secret-key-"
            "32-bytes-minimum"
        ),
        "environment": "test",
        "turn_enabled": True,
        "turn_shared_secret": "s" * 40,
        "turn_public_host": "nvr.example.test",
        "turn_port": 3478,
        "turn_credential_ttl_seconds": 600,
    }
    values.update(overrides)
    return Settings(**values)


def test_turn_rest_credential_matches_coturn_hmac_contract() -> None:
    user_id = uuid.UUID(
        "11111111-2222-3333-4444-555555555555"
    )
    bundle = TurnCredentialService(
        make_settings()
    ).issue(
        user_id=user_id,
        request_host="ignored.example.test",
        now_epoch=1_000,
    )
    assert bundle is not None
    assert bundle.username == (
        "1600:"
        "11111111-2222-3333-4444-555555555555"
    )
    expected = base64.b64encode(
        hmac.new(
            ("s" * 40).encode("utf-8"),
            bundle.username.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")
    assert bundle.credential == expected
    assert bundle.urls == [
        (
            "turn:nvr.example.test:3478"
            "?transport=udp"
        ),
        (
            "turn:nvr.example.test:3478"
            "?transport=tcp"
        ),
    ]
    assert int(
        bundle.expires_at.timestamp()
    ) == 1600


def test_turn_can_use_external_urls_or_stay_disabled() -> None:
    disabled = TurnCredentialService(
        make_settings(
            turn_enabled=False,
        )
    ).issue(
        user_id=uuid.uuid4(),
        request_host="nvr.example.test",
        now_epoch=1_000,
    )
    assert disabled is None

    external = TurnCredentialService(
        make_settings(
            turn_urls=(
                "turn:relay.example.test:3478"
                "?transport=udp,"
                "turns:relay.example.test:5349"
                "?transport=tcp"
            ),
            turn_public_host=None,
        )
    ).issue(
        user_id=uuid.uuid4(),
        request_host=None,
        now_epoch=2_000,
    )
    assert external is not None
    assert external.urls == [
        (
            "turn:relay.example.test:3478"
            "?transport=udp"
        ),
        (
            "turns:relay.example.test:5349"
            "?transport=tcp"
        ),
    ]


def test_turn_uses_request_host_when_public_host_is_not_set() -> None:
    bundle = TurnCredentialService(
        make_settings(
            turn_public_host=None,
            turn_port=5349,
        )
    ).issue(
        user_id=uuid.uuid4(),
        request_host="camera.example.test",
        now_epoch=3_000,
    )
    assert bundle is not None
    assert bundle.urls == [
        (
            "turn:camera.example.test:5349"
            "?transport=udp"
        ),
        (
            "turn:camera.example.test:5349"
            "?transport=tcp"
        ),
    ]
