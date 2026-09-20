from __future__ import annotations

import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.integrations.rclone import RcloneAdapter, RcloneIntegrationError
from app.modules.auth.models import SecretRecord
from app.modules.recordings.models import RecordingPolicy

from .models import RecordingLocation, StorageTarget


_REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class StorageTargetTestResult:
    type: str
    detail: str
    free_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedRcloneTarget:
    target_id: uuid.UUID
    remote: str
    base_path: str
    config_text: str

    def object_path(self, object_path: str) -> str:
        relative = object_path.strip("/")
        parts = [
            part
            for part in relative.split("/")
            if part
        ]
        if (
            not parts
            or any(
                part in {".", ".."}
                or ":" in part
                or "\\" in part
                for part in parts
            )
        ):
            raise ApiError(
                status_code=409,
                code="recording_object_path_invalid",
                message="Recording object path is invalid.",
            )

        prefix = self.base_path.strip("/")
        joined = "/".join(
            part
            for part in (prefix, "/".join(parts))
            if part
        )
        return f"{self.remote}:{joined}"


class StorageTargetService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.secret_store = SecretStore(settings)

    @staticmethod
    def _ensure_name_available(
        session: Session,
        *,
        name: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        statement = select(StorageTarget.id).where(
            StorageTarget.name == name
        )
        if exclude_id is not None:
            statement = statement.where(
                StorageTarget.id != exclude_id
            )
        if session.scalar(statement.limit(1)) is not None:
            raise ApiError(
                status_code=409,
                code="storage_target_name_conflict",
                message="Storage target name is already in use.",
            )

    @staticmethod
    def _ensure_default_recording_unique(
        session: Session,
        *,
        target_id: uuid.UUID | None,
        target_type: str,
        role: str,
        enabled: bool,
        config: dict[str, object],
    ) -> None:
        if not (
            target_type == "local"
            and role == "recording"
            and enabled
            and bool(config.get("default_recording"))
        ):
            return

        statement = select(StorageTarget.id).where(
            StorageTarget.type == "local",
            StorageTarget.role == "recording",
            StorageTarget.enabled.is_(True),
        )
        if target_id is not None:
            statement = statement.where(
                StorageTarget.id != target_id
            )

        for existing_id in session.scalars(statement):
            existing = session.get(StorageTarget, existing_id)
            if existing is not None and bool(
                (existing.config_json or {}).get("default_recording")
            ):
                raise ApiError(
                    status_code=409,
                    code="default_recording_target_conflict",
                    message="Only one enabled local recording target can be the default.",
                )

    @staticmethod
    def _ensure_default_archive_unique(
        session: Session,
        *,
        target_id: uuid.UUID | None,
        target_type: str,
        role: str,
        enabled: bool,
        config: dict[str, object],
    ) -> None:
        if not (
            target_type == "rclone"
            and role == "archive"
            and enabled
            and bool(config.get("default_archive"))
        ):
            return

        statement = select(StorageTarget.id).where(
            StorageTarget.type == "rclone",
            StorageTarget.role == "archive",
            StorageTarget.enabled.is_(True),
        )
        if target_id is not None:
            statement = statement.where(
                StorageTarget.id != target_id
            )

        for existing_id in session.scalars(statement):
            existing = session.get(StorageTarget, existing_id)
            if existing is not None and bool(
                (existing.config_json or {}).get("default_archive")
            ):
                raise ApiError(
                    status_code=409,
                    code="default_archive_target_conflict",
                    message="Only one enabled rclone archive target can be the default.",
                )

    @staticmethod
    def list(session: Session) -> list[StorageTarget]:
        return list(
            session.scalars(
                select(StorageTarget).order_by(
                    StorageTarget.name,
                    StorageTarget.id,
                )
            )
        )

    @staticmethod
    def get(
        session: Session,
        target_id: uuid.UUID,
    ) -> StorageTarget:
        target = session.get(StorageTarget, target_id)
        if target is None:
            raise ApiError(
                status_code=404,
                code="storage_target_not_found",
                message="Storage target was not found.",
            )
        return target

    @staticmethod
    def _local_config(
        *,
        role: str,
        config: dict[str, object],
    ) -> dict[str, object]:
        if set(config) - {"path", "default_recording"}:
            raise ApiError(
                status_code=400,
                code="storage_target_config_invalid",
                message="Local storage target contains unsupported configuration.",
            )
        raw_path = config.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ApiError(
                status_code=400,
                code="storage_target_path_required",
                message="Local storage target requires an absolute path.",
            )
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise ApiError(
                status_code=400,
                code="storage_target_path_invalid",
                message="Local storage target path must be absolute.",
            )
        default_recording = bool(config.get("default_recording", False))
        if role != "recording" and default_recording:
            raise ApiError(
                status_code=400,
                code="storage_target_config_invalid",
                message="Only a recording target can be the default recording target.",
            )
        return {
            "path": str(path.resolve(strict=False)),
            "default_recording": default_recording,
        }

    @staticmethod
    def _rclone_config(
        *,
        role: str,
        config: dict[str, object],
    ) -> dict[str, object]:
        if role != "archive":
            raise ApiError(
                status_code=400,
                code="storage_target_role_invalid",
                message="rclone targets are archive targets; cameras always record locally first.",
            )
        if set(config) - {"remote", "base_path", "default_archive"}:
            raise ApiError(
                status_code=400,
                code="storage_target_config_invalid",
                message="rclone target contains unsupported configuration.",
            )
        remote = config.get("remote")
        if not isinstance(remote, str) or not _REMOTE_RE.fullmatch(remote.strip()):
            raise ApiError(
                status_code=400,
                code="rclone_remote_invalid",
                message="rclone remote name is invalid.",
            )
        raw_base = config.get("base_path", "")
        if not isinstance(raw_base, str):
            raise ApiError(
                status_code=400,
                code="rclone_base_path_invalid",
                message="rclone archive base path is invalid.",
            )
        base = raw_base.strip().strip("/")
        parts = [part for part in base.split("/") if part]
        if any(
            part in {".", ".."}
            or ":" in part
            or "\\" in part
            for part in parts
        ):
            raise ApiError(
                status_code=400,
                code="rclone_base_path_invalid",
                message="rclone archive base path is invalid.",
            )
        normalized: dict[str, object] = {
            "remote": remote.strip(),
            "base_path": "/".join(parts),
        }
        if bool(config.get("default_archive", False)):
            normalized["default_archive"] = True
        return normalized

    @classmethod
    def normalize_config(
        cls,
        *,
        target_type: str,
        role: str,
        config: dict[str, object],
    ) -> dict[str, object]:
        if target_type == "local":
            return cls._local_config(
                role=role,
                config=config,
            )
        if target_type == "rclone":
            return cls._rclone_config(
                role=role,
                config=config,
            )
        raise ApiError(
            status_code=400,
            code="storage_target_type_invalid",
            message="Storage target type is invalid.",
        )

    def _replace_rclone_secret(
        self,
        session: Session,
        *,
        target: StorageTarget,
        config_text: str,
    ) -> None:
        if not config_text.strip():
            raise ApiError(
                status_code=400,
                code="rclone_config_invalid",
                message="rclone configuration cannot be empty.",
            )
        encrypted = self.secret_store.encrypt_json(
            {"config": config_text}
        )
        secret = (
            session.get(
                SecretRecord,
                target.credential_secret_ref,
            )
            if target.credential_secret_ref is not None
            else None
        )
        if secret is None:
            secret = SecretRecord(
                kind="rclone_config",
                owner_type="storage_target",
                owner_id=target.id,
                key_id=encrypted.key_id,
                encrypted_payload=encrypted.ciphertext,
                version=encrypted.version,
            )
            session.add(secret)
            session.flush()
            target.credential_secret_ref = secret.id
        else:
            secret.key_id = encrypted.key_id
            secret.encrypted_payload = encrypted.ciphertext
            secret.version = encrypted.version

    def create(
        self,
        session: Session,
        *,
        target_type: str,
        role: str,
        name: str,
        enabled: bool,
        config: dict[str, object],
        rclone_config: str | None,
    ) -> StorageTarget:
        normalized = self.normalize_config(
            target_type=target_type,
            role=role,
            config=config,
        )
        normalized_name = name.strip()
        self._ensure_name_available(
            session,
            name=normalized_name,
        )
        self._ensure_default_recording_unique(
            session,
            target_id=None,
            target_type=target_type,
            role=role,
            enabled=enabled,
            config=normalized,
        )
        self._ensure_default_archive_unique(
            session,
            target_id=None,
            target_type=target_type,
            role=role,
            enabled=enabled,
            config=normalized,
        )

        target = StorageTarget(
            type=target_type,
            role=role,
            name=normalized_name,
            enabled=enabled,
            config_json=normalized,
        )
        session.add(target)
        session.flush()

        if target_type == "rclone":
            if rclone_config is None:
                raise ApiError(
                    status_code=400,
                    code="rclone_config_required",
                    message="rclone target requires credential configuration.",
                )
            self._replace_rclone_secret(
                session,
                target=target,
                config_text=rclone_config,
            )
        elif rclone_config is not None:
            raise ApiError(
                status_code=400,
                code="storage_target_credentials_not_allowed",
                message="Local storage target does not use rclone credentials.",
            )

        session.flush()
        return target

    def update(
        self,
        session: Session,
        *,
        target: StorageTarget,
        changes: dict[str, object],
    ) -> StorageTarget:
        if "name" in changes:
            name = changes["name"]
            if not isinstance(name, str) or not name.strip():
                raise ApiError(
                    status_code=400,
                    code="storage_target_name_invalid",
                    message="Storage target name is invalid.",
                )
            normalized_name = name.strip()
            self._ensure_name_available(
                session,
                name=normalized_name,
                exclude_id=target.id,
            )
            target.name = normalized_name

        if "enabled" in changes:
            target.enabled = bool(changes["enabled"])

        if "config" in changes:
            config = changes["config"]
            if not isinstance(config, dict):
                raise ApiError(
                    status_code=400,
                    code="storage_target_config_invalid",
                    message="Storage target configuration is invalid.",
                )
            target.config_json = self.normalize_config(
                target_type=target.type,
                role=target.role,
                config=config,
            )

        self._ensure_default_recording_unique(
            session,
            target_id=target.id,
            target_type=target.type,
            role=target.role,
            enabled=target.enabled,
            config=target.config_json or {},
        )
        self._ensure_default_archive_unique(
            session,
            target_id=target.id,
            target_type=target.type,
            role=target.role,
            enabled=target.enabled,
            config=target.config_json or {},
        )

        if "rclone_config" in changes:
            if target.type != "rclone":
                raise ApiError(
                    status_code=400,
                    code="storage_target_credentials_not_allowed",
                    message="Local storage target does not use rclone credentials.",
                )
            raw = changes["rclone_config"]
            if not isinstance(raw, str):
                raise ApiError(
                    status_code=400,
                    code="rclone_config_invalid",
                    message="rclone configuration cannot be cleared with PATCH.",
                )
            self._replace_rclone_secret(
                session,
                target=target,
                config_text=raw,
            )

        session.flush()
        return target

    @staticmethod
    def delete(
        session: Session,
        *,
        target: StorageTarget,
    ) -> None:
        location = session.scalar(
            select(RecordingLocation.id)
            .where(
                RecordingLocation.storage_target_id == target.id
            )
            .limit(1)
        )
        policy = session.scalar(
            select(RecordingPolicy.id)
            .where(
                RecordingPolicy.storage_target_id == target.id
            )
            .limit(1)
        )
        if location is not None or policy is not None:
            raise ApiError(
                status_code=409,
                code="storage_target_in_use",
                message="Storage target is referenced by recording data or policy.",
            )

        secret_id = target.credential_secret_ref
        session.delete(target)
        session.flush()
        if secret_id is not None:
            secret = session.get(SecretRecord, secret_id)
            if secret is not None:
                session.delete(secret)

    def resolve_rclone(
        self,
        session: Session,
        *,
        target: StorageTarget,
    ) -> ResolvedRcloneTarget:
        if (
            target.type != "rclone"
            or target.role != "archive"
            or not target.enabled
        ):
            raise ApiError(
                status_code=409,
                code="rclone_target_unavailable",
                message="rclone archive target is unavailable.",
            )
        if target.credential_secret_ref is None:
            raise ApiError(
                status_code=409,
                code="rclone_credentials_missing",
                message="rclone archive credentials are unavailable.",
            )
        secret = session.get(
            SecretRecord,
            target.credential_secret_ref,
        )
        if secret is None:
            raise ApiError(
                status_code=409,
                code="rclone_credentials_missing",
                message="rclone archive credentials are unavailable.",
            )
        try:
            payload = self.secret_store.decrypt_json(
                key_id=secret.key_id,
                ciphertext=secret.encrypted_payload,
                version=secret.version,
            )
        except Exception as exc:
            raise ApiError(
                status_code=409,
                code="rclone_credentials_unavailable",
                message="rclone archive credentials could not be decrypted.",
            ) from exc

        config_text = payload.get("config")
        config = target.config_json or {}
        remote = config.get("remote")
        base_path = config.get("base_path", "")
        if (
            not isinstance(config_text, str)
            or not isinstance(remote, str)
            or not isinstance(base_path, str)
        ):
            raise ApiError(
                status_code=409,
                code="rclone_target_invalid",
                message="rclone archive target configuration is invalid.",
            )
        return ResolvedRcloneTarget(
            target_id=target.id,
            remote=remote,
            base_path=base_path,
            config_text=config_text,
        )

    def test_target(
        self,
        *,
        target_type: str,
        config: dict[str, object],
        rclone_config: str | None,
    ) -> StorageTargetTestResult:
        if target_type == "local":
            raw_path = config.get("path")
            if not isinstance(raw_path, str):
                raise ApiError(
                    status_code=409,
                    code="storage_target_path_invalid",
                    message="Local storage target path is invalid.",
                )
            root = Path(raw_path)
            if not root.is_dir():
                raise ApiError(
                    status_code=409,
                    code="storage_target_path_unavailable",
                    message="Local storage target path is not mounted or is not a directory.",
                )
            try:
                with tempfile.NamedTemporaryFile(
                    dir=root,
                    prefix=".zero-nvr-storage-test-",
                    delete=True,
                ) as handle:
                    handle.write(b"zero-nvr")
                    handle.flush()
                    os.fsync(handle.fileno())
                stats = os.statvfs(root)
            except OSError as exc:
                raise ApiError(
                    status_code=409,
                    code="storage_target_not_writable",
                    message="Local storage target is not writable.",
                ) from exc
            return StorageTargetTestResult(
                type="local",
                detail="read_write_ok",
                free_bytes=stats.f_bavail * stats.f_frsize,
            )

        if rclone_config is None:
            raise ApiError(
                status_code=409,
                code="rclone_credentials_missing",
                message="rclone archive credentials are unavailable.",
            )
        remote = config.get("remote")
        base_path = config.get("base_path", "")
        if not isinstance(remote, str) or not isinstance(base_path, str):
            raise ApiError(
                status_code=409,
                code="rclone_target_invalid",
                message="rclone archive target configuration is invalid.",
            )

        with tempfile.NamedTemporaryFile(
            dir=self.settings.cache_dir,
            prefix="zero-nvr-rclone-test-",
            delete=False,
        ) as handle:
            local_path = Path(handle.name)
            handle.write(b"zero-nvr-rclone-probe")
            handle.flush()
            os.fsync(handle.fileno())

        probe_name = f".zero-nvr-probe/{uuid.uuid4().hex}"
        joined = "/".join(
            part
            for part in (base_path.strip("/"), probe_name)
            if part
        )
        remote_path = f"{remote}:{joined}"
        adapter = RcloneAdapter(
            config_text=rclone_config,
            binary=self.settings.rclone_binary,
            timeout_seconds=self.settings.rclone_timeout_seconds,
        )
        try:
            adapter.copy_to_remote(
                source=local_path,
                destination=remote_path,
                expected_size=local_path.stat().st_size,
            )
            adapter.delete_file(remote_path)
        except RcloneIntegrationError as exc:
            raise ApiError(
                status_code=exc.status_code,
                code=exc.code,
                message=str(exc),
            ) from exc
        finally:
            local_path.unlink(missing_ok=True)

        return StorageTargetTestResult(
            type="rclone",
            detail="read_write_delete_ok",
        )
