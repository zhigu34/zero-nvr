from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import SecretStore
from app.modules.auth.models import SecretRecord


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


def test_secret_store_database_boundary_crud() -> None:
    engine = create_engine("sqlite:///:memory:")
    SecretRecord.__table__.create(engine)
    store = SecretStore(Settings(secret_key=NEW_KEY))
    owner_id = uuid.uuid4()

    try:
        with Session(engine) as session:
            secret_ref = store.create_json(
                session,
                kind="test_credential",
                owner_type="test_owner",
                owner_id=owner_id,
                value={
                    "username": "camera-admin",
                    "password": "database-secret",
                },
            )
            session.commit()

        with Session(engine) as session:
            record = session.get(
                SecretRecord,
                secret_ref,
            )
            assert record is not None
            assert b"database-secret" not in record.encrypted_payload

            metadata = store.metadata(
                session,
                secret_ref,
                kind="test_credential",
                owner_type="test_owner",
                owner_id=owner_id,
            )
            assert metadata.secret_ref == secret_ref
            assert metadata.kind == "test_credential"
            assert not metadata.needs_rotation

            assert store.read_json(
                session,
                secret_ref,
                kind="test_credential",
                owner_type="test_owner",
                owner_id=owner_id,
            ) == {
                "password": "database-secret",
                "username": "camera-admin",
            }

            with pytest.raises(
                KeyError,
                match="record is unavailable",
            ):
                store.read_json(
                    session,
                    secret_ref,
                    kind="test_credential",
                    owner_type="test_owner",
                    owner_id=uuid.uuid4(),
                )

            store.replace_json(
                session,
                secret_ref,
                kind="test_credential",
                owner_type="test_owner",
                owner_id=owner_id,
                value={"password": "replacement-secret"},
            )
            session.commit()

        with Session(engine) as session:
            assert store.read_json(
                session,
                secret_ref,
                kind="test_credential",
                owner_type="test_owner",
                owner_id=owner_id,
            ) == {"password": "replacement-secret"}

            store.delete(
                session,
                secret_ref,
                kind="test_credential",
                owner_type="test_owner",
                owner_id=owner_id,
            )
            session.commit()
            assert session.get(SecretRecord, secret_ref) is None
    finally:
        engine.dispose()


def test_secret_store_persists_across_process_recreation(
    tmp_path,
) -> None:
    database_path = tmp_path / "secrets.db"
    database_url = f"sqlite:///{database_path}"
    owner_id = uuid.uuid4()

    engine = create_engine(database_url)
    SecretRecord.__table__.create(engine)
    try:
        first_store = SecretStore(
            Settings(secret_key=NEW_KEY)
        )
        with Session(engine) as session:
            secret_ref = first_store.create_json(
                session,
                kind="restart_credential",
                owner_type="test_owner",
                owner_id=owner_id,
                value={
                    "username": "camera-admin",
                    "password": "persistent-secret",
                },
            )
            session.commit()
    finally:
        engine.dispose()

    reopened_engine = create_engine(database_url)
    try:
        second_store = SecretStore(
            Settings(secret_key=NEW_KEY)
        )
        with Session(reopened_engine) as session:
            assert second_store.read_json(
                session,
                secret_ref,
                kind="restart_credential",
                owner_type="test_owner",
                owner_id=owner_id,
            ) == {
                "password": "persistent-secret",
                "username": "camera-admin",
            }

            record = session.get(
                SecretRecord,
                secret_ref,
            )
            assert record is not None
            assert (
                b"persistent-secret"
                not in record.encrypted_payload
            )
    finally:
        reopened_engine.dispose()


def test_secret_store_rotates_persisted_records_to_primary_key() -> None:
    engine = create_engine("sqlite:///:memory:")
    SecretRecord.__table__.create(engine)
    owner_id = uuid.uuid4()

    try:
        old_store = SecretStore(
            Settings(secret_key=OLD_KEY)
        )
        with Session(engine) as session:
            secret_ref = old_store.create_json(
                session,
                kind="rotation_credential",
                owner_type="test_owner",
                owner_id=owner_id,
                value={"password": "rotate-me"},
            )
            session.commit()

        rotating_store = SecretStore(
            Settings(
                secret_key=NEW_KEY,
                secret_key_previous=[OLD_KEY],
            )
        )
        with Session(engine) as session:
            result = rotating_store.rotate_records(
                session
            )
            session.commit()

        assert result.total_records == 1
        assert result.rotated_records == 1
        assert result.current_records == 0
        assert (
            result.primary_key_id
            == rotating_store.primary_key_id
        )

        new_only_store = SecretStore(
            Settings(secret_key=NEW_KEY)
        )
        with Session(engine) as session:
            assert new_only_store.read_json(
                session,
                secret_ref,
                kind="rotation_credential",
                owner_type="test_owner",
                owner_id=owner_id,
            ) == {"password": "rotate-me"}
            metadata = new_only_store.metadata(
                session,
                secret_ref,
            )
            assert not metadata.needs_rotation
    finally:
        engine.dispose()


def test_secret_store_rotation_fails_before_mutation_without_old_key() -> None:
    engine = create_engine("sqlite:///:memory:")
    SecretRecord.__table__.create(engine)
    owner_id = uuid.uuid4()

    try:
        old_store = SecretStore(
            Settings(secret_key=OLD_KEY)
        )
        with Session(engine) as session:
            secret_ref = old_store.create_json(
                session,
                kind="rotation_credential",
                owner_type="test_owner",
                owner_id=owner_id,
                value={"password": "still-old"},
            )
            session.commit()

        new_only_store = SecretStore(
            Settings(secret_key=NEW_KEY)
        )
        with Session(engine) as session:
            with pytest.raises(
                KeyError,
                match="key is unavailable",
            ):
                new_only_store.rotate_records(session)
            session.rollback()

        with Session(engine) as session:
            assert old_store.read_json(
                session,
                secret_ref,
                kind="rotation_credential",
                owner_type="test_owner",
                owner_id=owner_id,
            ) == {"password": "still-old"}
    finally:
        engine.dispose()
