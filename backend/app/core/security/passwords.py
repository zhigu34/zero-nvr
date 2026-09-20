from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


class PasswordPolicyError(ValueError):
    pass


class PasswordService:
    """Local-account password hashing and verification.

    The hashing implementation is delegated to pwdlib's recommended Argon2
    configuration. Product password-policy settings can later wrap this
    service without changing stored hash semantics.
    """

    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()

    @staticmethod
    def validate_new_password(password: str) -> None:
        if len(password) < 12:
            raise PasswordPolicyError("password must be at least 12 characters")
        if len(password) > 1024:
            raise PasswordPolicyError("password is too long")

    def hash_password(self, password: str) -> str:
        self.validate_new_password(password)
        return self._password_hash.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return self._password_hash.verify(password, password_hash)
        except UnknownHashError:
            return False

    def verify_and_update(
        self,
        password: str,
        password_hash: str,
    ) -> tuple[bool, str | None]:
        try:
            return self._password_hash.verify_and_update(password, password_hash)
        except UnknownHashError:
            return False, None
