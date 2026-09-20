from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.security import SecretStore


NEW_KEY = "n" * 40
OLD_KEY = "o" * 40


def test_secret_store_round_trip() -> None:
    store = SecretStore(Settings(secret_key=NEW_KEY))

    encrypted = store.encrypt_json(
        {
            "username": "camera-admin",
            "password": "sensitive-value",
        }
    )

    assert encrypted.key_id == store.primary_key_id
    assert b"sensitive-value" not in encrypted.ciphertext
    assert store.decrypt_json(
        key_id=encrypted.key_id,
        ciphertext=encrypted.ciphertext,
        version=encrypted.version,
    ) == {
        "password": "sensitive-value",
        "username": "camera-admin",
    }


def test_previous_key_can_decrypt_and_rotate() -> None:
    old_store = SecretStore(Settings(secret_key=OLD_KEY))
    old_value = old_store.encrypt_bytes(b"legacy-secret")

    store = SecretStore(
        Settings(
            secret_key=NEW_KEY,
            secret_key_previous=[OLD_KEY],
        )
    )

    assert store.needs_rotation(old_value.key_id)
    assert store.decrypt_bytes(
        key_id=old_value.key_id,
        ciphertext=old_value.ciphertext,
    ) == b"legacy-secret"

    rotated = store.rotate(
        key_id=old_value.key_id,
        ciphertext=old_value.ciphertext,
    )

    assert rotated.key_id == store.primary_key_id
    assert not store.needs_rotation(rotated.key_id)
    assert store.decrypt_bytes(
        key_id=rotated.key_id,
        ciphertext=rotated.ciphertext,
    ) == b"legacy-secret"


def test_tampering_fails_authentication() -> None:
    store = SecretStore(Settings(secret_key=NEW_KEY))
    encrypted = store.encrypt_bytes(b"secret")

    tampered = bytearray(encrypted.ciphertext)
    tampered[-2] ^= 1

    with pytest.raises(ValueError, match="authentication failed"):
        store.decrypt_bytes(
            key_id=encrypted.key_id,
            ciphertext=bytes(tampered),
        )


def test_missing_old_key_fails_explicitly() -> None:
    old_store = SecretStore(Settings(secret_key=OLD_KEY))
    old_value = old_store.encrypt_bytes(b"legacy-secret")

    new_store = SecretStore(Settings(secret_key=NEW_KEY))

    with pytest.raises(KeyError, match="key is unavailable"):
        new_store.decrypt_bytes(
            key_id=old_value.key_id,
            ciphertext=old_value.ciphertext,
        )
