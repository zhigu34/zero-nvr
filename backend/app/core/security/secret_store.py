from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import SecretStr

from app.core.config import Settings


_CONTEXT = b"zero-nvr/secret-store/v1"


@dataclass(frozen=True, slots=True)
class EncryptedSecret:
    key_id: str
    ciphertext: bytes
    version: int = 1


@dataclass(frozen=True, slots=True)
class SecretMetadata:
    secret_ref: uuid.UUID
    kind: str
    owner_type: str
    owner_id: uuid.UUID
    key_id: str
    version: int
    needs_rotation: bool


class SecretStore:
    """Authenticated encryption keyring for recoverable product secrets.

    The deployment bootstrap secret stays outside the product database.
    SecretRecord persists only key_id + ciphertext + version.
    """

    def __init__(self, settings: Settings) -> None:
        ordered = [settings.secret_key, *settings.secret_key_previous]
        self._keys: dict[str, Fernet] = {}

        for value in ordered:
            key_id, fernet = self._build_key(value)
            if key_id in self._keys:
                continue
            self._keys[key_id] = fernet

        if not self._keys:
            raise ValueError("SecretStore requires at least one key")

        self.primary_key_id = next(iter(self._keys))

    @staticmethod
    def _build_key(value: SecretStr) -> tuple[str, Fernet]:
        raw = value.get_secret_value().encode("utf-8")
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=_CONTEXT,
        ).derive(raw)

        key_id = hashlib.sha256(derived).hexdigest()[:16]
        fernet_key = base64.urlsafe_b64encode(derived)
        return key_id, Fernet(fernet_key)

    def encrypt_bytes(self, plaintext: bytes) -> EncryptedSecret:
        cipher = self._keys[self.primary_key_id]
        return EncryptedSecret(
            key_id=self.primary_key_id,
            ciphertext=cipher.encrypt(plaintext),
            version=1,
        )

    def decrypt_bytes(
        self,
        *,
        key_id: str,
        ciphertext: bytes,
        version: int = 1,
    ) -> bytes:
        if version != 1:
            raise ValueError(f"unsupported SecretStore version: {version}")

        cipher = self._keys.get(key_id)
        if cipher is None:
            raise KeyError(f"SecretStore key is unavailable: {key_id}")

        try:
            return cipher.decrypt(ciphertext)
        except InvalidToken as exc:
            raise ValueError("SecretStore ciphertext authentication failed") from exc

    def encrypt_json(self, value: dict[str, Any]) -> EncryptedSecret:
        plaintext = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.encrypt_bytes(plaintext)

    def decrypt_json(
        self,
        *,
        key_id: str,
        ciphertext: bytes,
        version: int = 1,
    ) -> dict[str, Any]:
        plaintext = self.decrypt_bytes(
            key_id=key_id,
            ciphertext=ciphertext,
            version=version,
        )
        value = json.loads(plaintext.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("SecretStore JSON payload must be an object")
        return value

    def needs_rotation(self, key_id: str) -> bool:
        return key_id != self.primary_key_id

    def rotate(
        self,
        *,
        key_id: str,
        ciphertext: bytes,
        version: int = 1,
    ) -> EncryptedSecret:
        plaintext = self.decrypt_bytes(
            key_id=key_id,
            ciphertext=ciphertext,
            version=version,
        )
        return self.encrypt_bytes(plaintext)

    @staticmethod
    def _secret_record_type() -> type[Any]:
        # Import lazily so the crypto/bootstrap boundary remains usable without
        # importing the full product model graph at module import time.
        from app.modules.auth.models import SecretRecord

        return SecretRecord

    def _record(
        self,
        session: Session,
        secret_ref: uuid.UUID,
        *,
        kind: str | None = None,
        owner_type: str | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> Any:
        record_type = self._secret_record_type()
        record = session.get(record_type, secret_ref)
        if (
            record is None
            or (kind is not None and record.kind != kind)
            or (
                owner_type is not None
                and record.owner_type != owner_type
            )
            or (
                owner_id is not None
                and record.owner_id != owner_id
            )
        ):
            raise KeyError(
                f"SecretStore record is unavailable: {secret_ref}"
            )
        return record

    def create(
        self,
        session: Session,
        *,
        kind: str,
        owner_type: str,
        owner_id: uuid.UUID,
        plaintext: bytes,
    ) -> uuid.UUID:
        encrypted = self.encrypt_bytes(plaintext)
        record_type = self._secret_record_type()
        record = record_type(
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
            key_id=encrypted.key_id,
            encrypted_payload=encrypted.ciphertext,
            version=encrypted.version,
        )
        session.add(record)
        session.flush()
        return record.id

    def read(
        self,
        session: Session,
        secret_ref: uuid.UUID,
        *,
        kind: str | None = None,
        owner_type: str | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> bytes:
        record = self._record(
            session,
            secret_ref,
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        return self.decrypt_bytes(
            key_id=record.key_id,
            ciphertext=record.encrypted_payload,
            version=record.version,
        )

    def replace(
        self,
        session: Session,
        secret_ref: uuid.UUID,
        *,
        plaintext: bytes,
        kind: str | None = None,
        owner_type: str | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> None:
        record = self._record(
            session,
            secret_ref,
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        encrypted = self.encrypt_bytes(plaintext)
        record.key_id = encrypted.key_id
        record.encrypted_payload = encrypted.ciphertext
        record.version = encrypted.version
        session.flush()

    def delete(
        self,
        session: Session,
        secret_ref: uuid.UUID,
        *,
        kind: str | None = None,
        owner_type: str | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> None:
        record = self._record(
            session,
            secret_ref,
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        session.delete(record)
        session.flush()

    def metadata(
        self,
        session: Session,
        secret_ref: uuid.UUID,
        *,
        kind: str | None = None,
        owner_type: str | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> SecretMetadata:
        record = self._record(
            session,
            secret_ref,
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        return SecretMetadata(
            secret_ref=record.id,
            kind=record.kind,
            owner_type=record.owner_type,
            owner_id=record.owner_id,
            key_id=record.key_id,
            version=record.version,
            needs_rotation=self.needs_rotation(record.key_id),
        )

    def create_json(
        self,
        session: Session,
        *,
        kind: str,
        owner_type: str,
        owner_id: uuid.UUID,
        value: dict[str, Any],
    ) -> uuid.UUID:
        plaintext = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.create(
            session,
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
            plaintext=plaintext,
        )

    def read_json(
        self,
        session: Session,
        secret_ref: uuid.UUID,
        *,
        kind: str | None = None,
        owner_type: str | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        plaintext = self.read(
            session,
            secret_ref,
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        value = json.loads(plaintext.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError(
                "SecretStore JSON payload must be an object"
            )
        return value

    def replace_json(
        self,
        session: Session,
        secret_ref: uuid.UUID,
        *,
        value: dict[str, Any],
        kind: str | None = None,
        owner_type: str | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> None:
        plaintext = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.replace(
            session,
            secret_ref,
            plaintext=plaintext,
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
        )
