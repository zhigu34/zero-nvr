from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError

from .models import BackupPolicy
from .service import BackupPolicyService


_AAD = b"zero-nvr/recovery-kit/v1"
_FORMAT = "zero-nvr.recovery-kit.encrypted"
_STATUS_FILE = "recovery-kit-status.json"
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1


@dataclass(frozen=True, slots=True)
class RecoveryKitStatus:
    status: Literal["never_generated", "current", "stale"]
    policy_id: uuid.UUID
    generated_at: datetime | None
    app_version: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class RecoveryKitArtifact:
    content: bytes
    filename: str
    generated_at: datetime
    status: RecoveryKitStatus


class RecoveryKitService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def _status_path(self) -> Path:
        return self.settings.data_dir / _STATUS_FILE

    @staticmethod
    def _secret_value(value) -> str:
        if value is None:
            return ""
        return value.get_secret_value()

    @staticmethod
    def _dotenv_line(
        key: str,
        value: str,
    ) -> str:
        return f"{key}={json.dumps(value, ensure_ascii=False)}"

    def _bootstrap_env(self) -> str:
        zlm_api_secret = self._secret_value(
            self.settings.zlm_api_secret
        )
        zlm_hook_secret = self._secret_value(
            self.settings.zlm_hook_secret
        )
        if (
            len(zlm_api_secret.encode("utf-8")) < 32
            or len(zlm_hook_secret.encode("utf-8")) < 32
        ):
            raise ApiError(
                status_code=409,
                code="recovery_kit_bootstrap_incomplete",
                message=(
                    "RecoveryKit generation requires the active "
                    "ZLMediaKit API and hook bootstrap secrets."
                ),
            )

        active_key = self.settings.secret_key.get_secret_value()
        previous_keys = [
            item.get_secret_value()
            for item in self.settings.secret_key_previous
        ]
        database_url = self.settings.database_url or ""

        profiles: list[str] = []
        postgres_values: dict[str, str] = {}
        if database_url:
            parsed = make_url(database_url)
            if (
                parsed.get_backend_name() == "postgresql"
                and parsed.host == "postgres"
            ):
                profiles.append("postgres")
                postgres_values = {
                    "ZERO_NVR_POSTGRES_DB": (
                        parsed.database or "zero_nvr"
                    ),
                    "ZERO_NVR_POSTGRES_USER": (
                        parsed.username or "zero_nvr"
                    ),
                    "ZERO_NVR_POSTGRES_PASSWORD": (
                        parsed.password or ""
                    ),
                }
        if self.settings.turn_enabled:
            profiles.append("turn")

        values = {
            "ZERO_NVR_DATA_PATH": "./data/zero-nvr",
            "ZERO_NVR_CACHE_PATH": "./data/cache",
            "ZERO_NVR_RECORDINGS_PATH": "./data/recordings",
            "ZERO_NVR_SECRET_KEY": active_key,
            "ZERO_NVR_SECRET_KEY_FILE": "",
            "ZERO_NVR_ZLM_API_SECRET": zlm_api_secret,
            "ZERO_NVR_ZLM_API_SECRET_FILE": "",
            "ZERO_NVR_ZLM_HOOK_SECRET": zlm_hook_secret,
            "ZERO_NVR_ZLM_HOOK_SECRET_FILE": "",
            "ZERO_NVR_ENVIRONMENT": self.settings.environment,
            "ZERO_NVR_SESSION_COOKIE_SECURE": (
                "true"
                if self.settings.session_cookie_secure
                else "false"
            ),
            "ZERO_NVR_ZLM_PUBLIC_BASE_URL": (
                self.settings.zlm_public_base_url
            ),
            "ZERO_NVR_TURN_ENABLED": (
                "true" if self.settings.turn_enabled else "false"
            ),
            "ZERO_NVR_TURN_URLS": self.settings.turn_urls,
            "ZERO_NVR_TURN_PUBLIC_HOST": (
                self.settings.turn_public_host or ""
            ),
            "ZERO_NVR_TURN_PORT": str(
                self.settings.turn_port
            ),
            "ZERO_NVR_TURN_SHARED_SECRET": self._secret_value(
                self.settings.turn_shared_secret
            ),
            "ZERO_NVR_TURN_SHARED_SECRET_FILE": "",
            "ZERO_NVR_TURN_REALM": self.settings.turn_realm,
            "ZERO_NVR_DATABASE_URL": database_url,
            "ZERO_NVR_PREBUFFER_SIZE": "512m",
            "COMPOSE_PROFILES": ",".join(profiles),
            **postgres_values,
        }

        lines = [
            "# zero-nvr RecoveryKit minimal clean-host bootstrap",
        ]
        for key, value in values.items():
            lines.append(self._dotenv_line(key, value))
        lines.append(
            "ZERO_NVR_SECRET_KEY_PREVIOUS="
            + json.dumps(
                previous_keys,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _recovery_env(
        *,
        repository: str,
        password: str,
        environment: dict[str, str],
    ) -> str:
        lines = [
            "# zero-nvr RecoveryKit restic bootstrap",
            RecoveryKitService._dotenv_line(
                "RESTIC_REPOSITORY",
                repository,
            ),
            RecoveryKitService._dotenv_line(
                "RESTIC_PASSWORD",
                password,
            ),
        ]
        for key, value in sorted(environment.items()):
            lines.append(
                RecoveryKitService._dotenv_line(
                    key,
                    value,
                )
            )
        return "\n".join(lines) + "\n"

    def _fingerprint(
        self,
        *,
        policy: BackupPolicy,
    ) -> str:
        secret_values = [
            self.settings.secret_key.get_secret_value(),
            *[
                item.get_secret_value()
                for item in self.settings.secret_key_previous
            ],
            self._secret_value(self.settings.zlm_api_secret),
            self._secret_value(self.settings.zlm_hook_secret),
            self._secret_value(
                self.settings.turn_shared_secret
            ),
        ]
        material = {
            "app_version": self.settings.app_version,
            "database_url": self.settings.database_url or "",
            "policy_id": str(policy.id),
            "policy_updated_at": (
                policy.updated_at.astimezone(UTC).isoformat()
            ),
            "repository_config_ref": str(
                policy.repository_config_ref
            ),
            "credential_secret_ref": (
                str(policy.credential_secret_ref)
                if policy.credential_secret_ref is not None
                else None
            ),
            "bootstrap_secret_hashes": [
                hashlib.sha256(
                    value.encode("utf-8")
                ).hexdigest()
                for value in secret_values
            ],
        }
        canonical = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _read_status(self) -> dict[str, object] | None:
        path = self._status_path
        if not path.is_file():
            return None
        try:
            value = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _write_status(
        self,
        *,
        policy_id: uuid.UUID,
        generated_at: datetime,
        fingerprint: str,
    ) -> None:
        path = self._status_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "version": 1,
                "policy_id": str(policy_id),
                "generated_at": (
                    generated_at.astimezone(UTC).isoformat()
                ),
                "app_version": self.settings.app_version,
                "fingerprint": fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        temp = path.with_name(
            f".{path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temp.write_text(
                payload,
                encoding="utf-8",
            )
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    def status(
        self,
        session: Session,
        *,
        policy: BackupPolicy,
    ) -> RecoveryKitStatus:
        fingerprint = self._fingerprint(
            policy=policy
        )
        state = self._read_status()
        generated_at = None
        current = False

        if state is not None:
            try:
                state_policy = uuid.UUID(
                    str(state["policy_id"])
                )
                generated_at = datetime.fromisoformat(
                    str(state["generated_at"])
                ).astimezone(UTC)
                state_fingerprint = str(
                    state["fingerprint"]
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                state_policy = None
                state_fingerprint = ""
                generated_at = None

            current = (
                state_policy == policy.id
                and state_fingerprint == fingerprint
            )

        if state is None or generated_at is None:
            status = "never_generated"
        elif current:
            status = "current"
        else:
            status = "stale"

        return RecoveryKitStatus(
            status=status,
            policy_id=policy.id,
            generated_at=generated_at,
            app_version=self.settings.app_version,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _derive_key(
        passphrase: str,
        *,
        salt: bytes,
    ) -> bytes:
        return Scrypt(
            salt=salt,
            length=32,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
        ).derive(
            passphrase.encode("utf-8")
        )

    def generate(
        self,
        session: Session,
        *,
        policy: BackupPolicy,
        passphrase: str,
    ) -> RecoveryKitArtifact:
        if len(passphrase.encode("utf-8")) < 16:
            raise ApiError(
                status_code=400,
                code="recovery_kit_passphrase_too_short",
                message=(
                    "RecoveryKit passphrase must be at "
                    "least 16 bytes."
                ),
            )

        resolved = BackupPolicyService(
            self.settings
        ).resolve(
            session,
            policy=policy,
        )
        generated_at = datetime.now(UTC)
        fingerprint = self._fingerprint(
            policy=policy
        )

        payload = {
            "format": "zero-nvr.recovery-kit",
            "version": 1,
            "generated_at": generated_at.isoformat(),
            "app_version": self.settings.app_version,
            "policy_id": str(policy.id),
            "fingerprint": fingerprint,
            "files": {
                "zero-nvr.env": self._bootstrap_env(),
                "recovery.env": self._recovery_env(
                    repository=resolved.repository,
                    password=resolved.password,
                    environment=resolved.environment,
                ),
                "README.txt": (
                    "zero-nvr encrypted RecoveryKit\n"
                    "==============================\n\n"
                    "Decrypt this package with the RecoveryKit "
                    "passphrase, then copy zero-nvr.env to .env "
                    "and recovery.env to deploy/recovery.env.\n"
                    "Run ./deploy.sh restore list before choosing "
                    "a restore point.\n"
                    "Keep this package and its passphrase off-host "
                    "and in separate protected locations.\n"
                ),
            },
        }
        plaintext = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = self._derive_key(
            passphrase,
            salt=salt,
        )
        ciphertext = AESGCM(key).encrypt(
            nonce,
            plaintext,
            _AAD,
        )
        envelope = {
            "format": _FORMAT,
            "version": 1,
            "kdf": {
                "name": "scrypt",
                "salt": base64.urlsafe_b64encode(
                    salt
                ).decode("ascii"),
                "n": _SCRYPT_N,
                "r": _SCRYPT_R,
                "p": _SCRYPT_P,
            },
            "cipher": {
                "name": "AES-256-GCM",
                "nonce": base64.urlsafe_b64encode(
                    nonce
                ).decode("ascii"),
                "ciphertext": base64.urlsafe_b64encode(
                    ciphertext
                ).decode("ascii"),
            },
        }
        content = (
            json.dumps(
                envelope,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        self._write_status(
            policy_id=policy.id,
            generated_at=generated_at,
            fingerprint=fingerprint,
        )
        status = self.status(
            session,
            policy=policy,
        )
        filename = (
            "zero-nvr-recovery-kit-"
            + generated_at.strftime("%Y%m%dT%H%M%SZ")
            + ".znrk"
        )
        return RecoveryKitArtifact(
            content=content,
            filename=filename,
            generated_at=generated_at,
            status=status,
        )

    @classmethod
    def decrypt(
        cls,
        content: bytes,
        *,
        passphrase: str,
    ) -> dict[str, object]:
        envelope = json.loads(
            content.decode("utf-8")
        )
        if (
            envelope.get("format") != _FORMAT
            or envelope.get("version") != 1
        ):
            raise ValueError(
                "unsupported RecoveryKit format"
            )
        kdf = envelope["kdf"]
        cipher = envelope["cipher"]
        if (
            kdf.get("name") != "scrypt"
            or cipher.get("name") != "AES-256-GCM"
        ):
            raise ValueError(
                "unsupported RecoveryKit crypto"
            )
        salt = base64.urlsafe_b64decode(
            kdf["salt"]
        )
        nonce = base64.urlsafe_b64decode(
            cipher["nonce"]
        )
        ciphertext = base64.urlsafe_b64decode(
            cipher["ciphertext"]
        )
        key = cls._derive_key(
            passphrase,
            salt=salt,
        )
        plaintext = AESGCM(key).decrypt(
            nonce,
            ciphertext,
            _AAD,
        )
        payload = json.loads(
            plaintext.decode("utf-8")
        )
        if (
            payload.get("format")
            != "zero-nvr.recovery-kit"
            or payload.get("version") != 1
        ):
            raise ValueError(
                "unsupported RecoveryKit payload"
            )
        return payload
