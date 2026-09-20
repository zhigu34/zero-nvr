from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from pwdlib import PasswordHash
from pydantic import SecretStr


_PASSWORD_HASH = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = _PASSWORD_HASH.hash(
    "zero-nvr-dummy-password-verification"
)
_SESSION_CONTEXT = b"zero-nvr/session/v1:"


class PasswordService:
    def hash(self, password: str) -> str:
        return _PASSWORD_HASH.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return _PASSWORD_HASH.verify(password, password_hash)
        except Exception:
            return False

    def verify_or_dummy(
        self,
        password: str,
        password_hash: str | None,
    ) -> bool:
        candidate = (
            password_hash
            if password_hash
            else _DUMMY_PASSWORD_HASH
        )
        valid = self.verify(
            password,
            candidate,
        )
        return bool(password_hash) and valid


class SessionSigner:
    """Sign an opaque persisted UserSession UUID for browser cookies."""

    def __init__(self, secret_key: SecretStr) -> None:
        self._key = hashlib.sha256(
            secret_key.get_secret_value().encode("utf-8")
        ).digest()

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)

    def sign(self, session_id: uuid.UUID) -> str:
        raw = session_id.bytes
        signature = hmac.new(
            self._key,
            _SESSION_CONTEXT + raw,
            hashlib.sha256,
        ).digest()
        return f"{self._encode(raw)}.{self._encode(signature)}"

    def verify(self, token: str) -> uuid.UUID | None:
        try:
            raw_part, signature_part = token.split(".", 1)
            raw = self._decode(raw_part)
            provided = self._decode(signature_part)
            if len(raw) != 16:
                return None
        except Exception:
            return None

        expected = hmac.new(
            self._key,
            _SESSION_CONTEXT + raw,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(provided, expected):
            return None

        return uuid.UUID(bytes=raw)
