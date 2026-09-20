from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

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
