from __future__ import annotations

import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.integrations.rclone import RcloneAdapter, RcloneIntegrationError
from app.modules.recordings.models import RecordingPolicy

from .capacity import LocalStorageCapacityService
from .models import RecordingLocation, StorageTarget


_REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class StorageTargetTestResult:
    type: str
    detail: str
    free_bytes: int | None = None
    total_bytes: int | None = None
    used_bytes: int | None = None
    used_percent: float | None = None
    capacity_level: str | None = None
    warning_percent: int | None = None
    high_percent: int | None = None
    critical_percent: int | None = None


@dataclass(frozen=True, slots=True)
class RecordingTargetSwitchResult:
    source_target_id: uuid.UUID
    destination_target_id: uuid.UUID
    explicit_policies_updated: int
    implicit_policies_rebound: int
    default_moved: bool
    affected_camera_ids: tuple[uuid.UUID, ...]


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
    def default_archive_target(
        session: Session,
    ) -> StorageTarget:
        candidates = list(
            session.scalars(
                select(StorageTarget).where(
                    StorageTarget.type == "rclone",
                    StorageTarget.role == "archive",
                    StorageTarget.enabled.is_(True),
                )
            )
        )
        defaults = [
            item
            for item in candidates
            if bool(
                (item.config_json or {}).get("default_archive")
            )
        ]
        if len(defaults) == 1:
            return defaults[0]
        if len(defaults) > 1:
            raise ApiError(
                status_code=409,
                code="archive_target_ambiguous",
                message="More than one default archive target is configured.",
            )
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise ApiError(
                status_code=409,
                code="archive_target_unconfigured",
                message="No enabled rclone archive target is configured.",
            )
        raise ApiError(
            status_code=409,
            code="archive_target_ambiguous",
            message="Multiple archive targets exist and none is selected as default.",
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
        supported = {
            "path",
            "default_recording",
            LocalStorageCapacityService.warning_key,
            LocalStorageCapacityService.high_key,
            LocalStorageCapacityService.critical_key,
        }
        if set(config) - supported:
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
        watermarks = (
            LocalStorageCapacityService
            .normalize_config(config)
        )
        return {
            "path": str(path.resolve(strict=False)),
            "default_recording": default_recording,
            **watermarks,
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
        if set(config) - {
            "remote",
            "base_path",
            "default_archive",
            "provider",
        }:
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
        provider = config.get("provider")
        if provider is not None:
            if provider not in {
                "custom",
                "openlist_webdav",
            }:
                raise ApiError(
                    status_code=400,
                    code="rclone_provider_invalid",
                    message="rclone archive provider is invalid.",
                )
            normalized["provider"] = provider
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

    def _openlist_rclone_config(
        self,
        *,
        config: dict[str, object],
        credentials: dict[str, str],
    ) -> str:
        remote = config.get("remote")
        if not isinstance(remote, str) or not _REMOTE_RE.fullmatch(remote):
            raise ApiError(
                status_code=400,
                code="rclone_remote_invalid",
                message="rclone remote name is invalid.",
            )

        url = str(credentials.get("url", "")).strip()
        username = str(
            credentials.get("username", "")
        ).strip()
        password = str(
            credentials.get("password", "")
        )
        if (
            not url
            or not username
            or not password
            or any(
                char in url or char in username
                for char in ("\n", "\r")
            )
            or "\n" in password
            or "\r" in password
        ):
            raise ApiError(
                status_code=400,
                code="openlist_webdav_credentials_invalid",
                message=(
                    "OpenList WebDAV URL, username, and password "
                    "are required."
                ),
            )

        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ApiError(
                status_code=400,
                code="openlist_webdav_url_invalid",
                message=(
                    "OpenList WebDAV URL must be an http(s) URL "
                    "without embedded credentials."
                ),
            )
        normalized_url = url.rstrip("/") + "/"

        try:
            obscured = RcloneAdapter.obscure_password(
                password,
                binary=self.settings.rclone_binary,
                timeout_seconds=min(
                    self.settings.rclone_timeout_seconds,
                    30.0,
                ),
            )
        except RcloneIntegrationError as exc:
            raise ApiError(
                status_code=exc.status_code,
                code=exc.code,
                message=str(exc),
            ) from exc

        return (
            f"[{remote}]\n"
            "type = webdav\n"
            f"url = {normalized_url}\n"
            "vendor = other\n"
            f"user = {username}\n"
            f"pass = {obscured}\n"
        )

    def _replace_rclone_secret(
        self,
        session: Session,
        *,
        target: StorageTarget,
        config_text: str,
        validate_config: dict[str, object] | None = None,
    ) -> None:
        if not config_text.strip():
            raise ApiError(
                status_code=400,
                code="rclone_config_invalid",
                message="rclone configuration cannot be empty.",
            )
        if validate_config is not None:
            self.test_target(
                target_type="rclone",
                config=validate_config,
                rclone_config=config_text,
            )

        old_ref = target.credential_secret_ref
        if old_ref is not None:
            try:
                metadata = self.secret_store.metadata(
                    session,
                    old_ref,
                )
            except KeyError:
                old_ref = None
            else:
                if (
                    metadata.kind != "rclone_config"
                    or metadata.owner_type != "storage_target"
                    or metadata.owner_id != target.id
                ):
                    raise ApiError(
                        status_code=409,
                        code="rclone_credentials_unavailable",
                        message="rclone archive credentials are unavailable.",
                    )

        candidate_ref = self.secret_store.create_json(
            session,
            kind="rclone_config",
            owner_type="storage_target",
            owner_id=target.id,
            value={"config": config_text},
        )
        target.credential_secret_ref = candidate_ref
        session.flush()

        if old_ref is not None:
            try:
                self.secret_store.delete(
                    session,
                    old_ref,
                    kind="rclone_config",
                    owner_type="storage_target",
                    owner_id=target.id,
                )
            except KeyError:
                pass

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
        openlist_webdav: dict[str, str] | None = None,
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
            if (
                rclone_config is not None
                and openlist_webdav is not None
            ):
                raise ApiError(
                    status_code=400,
                    code="rclone_config_conflict",
                    message=(
                        "Provide either raw rclone configuration "
                        "or OpenList WebDAV credentials, not both."
                    ),
                )
            if openlist_webdav is not None:
                normalized = dict(
                    target.config_json or {}
                )
                normalized["provider"] = (
                    "openlist_webdav"
                )
                target.config_json = normalized
                rclone_config = (
                    self._openlist_rclone_config(
                        config=normalized,
                        credentials=openlist_webdav,
                    )
                )
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
        openlist_webdav = changes.pop(
            "openlist_webdav",
            None,
        )
        if (
            openlist_webdav is not None
            and not isinstance(
                openlist_webdav,
                dict,
            )
        ):
            raise ApiError(
                status_code=400,
                code="openlist_webdav_credentials_invalid",
                message="OpenList WebDAV credentials are invalid.",
            )

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
            normalized = self.normalize_config(
                target_type=target.type,
                role=target.role,
                config=config,
            )
            if (
                target.type == "local"
                and target.role == "recording"
            ):
                current_path = (
                    target.config_json or {}
                ).get("path")
                next_path = normalized.get("path")
                if (
                    isinstance(current_path, str)
                    and isinstance(next_path, str)
                    and current_path != next_path
                ):
                    raise ApiError(
                        status_code=409,
                        code="storage_target_path_immutable",
                        message=(
                            "Recording target paths cannot be changed in place. "
                            "Create another local target and switch recording "
                            "routing so historical RecordingLocations keep "
                            "their original target identity."
                        ),
                    )
            target.config_json = normalized

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

        credential_action = str(
            changes.get(
                "rclone_config_action",
                "keep",
            )
        )
        if credential_action not in {
            "keep",
            "replace",
            "clear",
        }:
            raise ApiError(
                status_code=400,
                code="rclone_config_update_invalid",
                message="rclone credential action is invalid.",
            )

        if credential_action != "keep":
            if target.type != "rclone":
                raise ApiError(
                    status_code=400,
                    code="storage_target_credentials_not_allowed",
                    message="Local storage target does not use rclone credentials.",
                )

        if credential_action == "replace":
            raw = changes.get("rclone_config")
            if (
                raw is not None
                and openlist_webdav is not None
            ):
                raise ApiError(
                    status_code=400,
                    code="rclone_config_conflict",
                    message=(
                        "Provide either raw rclone configuration "
                        "or OpenList WebDAV credentials, not both."
                    ),
                )
            if openlist_webdav is not None:
                config = dict(
                    target.config_json or {}
                )
                config["provider"] = (
                    "openlist_webdav"
                )
                target.config_json = config
                raw = self._openlist_rclone_config(
                    config=config,
                    credentials={
                        str(key): str(value)
                        for key, value
                        in openlist_webdav.items()
                    },
                )
            if not isinstance(raw, str):
                raise ApiError(
                    status_code=400,
                    code="rclone_config_invalid",
                    message="rclone configuration is invalid.",
                )
            self._replace_rclone_secret(
                session,
                target=target,
                config_text=raw,
                validate_config=(
                    target.config_json or {}
                ),
            )
        elif credential_action == "clear":
            if "rclone_config" in changes:
                raise ApiError(
                    status_code=400,
                    code="rclone_config_update_invalid",
                    message=(
                        "rclone credential clear action "
                        "does not accept a replacement value."
                    ),
                )
            secret_ref = target.credential_secret_ref
            target.credential_secret_ref = None
            session.flush()
            if secret_ref is not None:
                try:
                    self.secret_store.delete(
                        session,
                        secret_ref,
                        kind="rclone_config",
                        owner_type="storage_target",
                        owner_id=target.id,
                    )
                except KeyError:
                    pass
        elif (
            "rclone_config" in changes
            or openlist_webdav is not None
        ):
            raise ApiError(
                status_code=400,
                code="rclone_config_update_invalid",
                message=(
                    "rclone credential value requires "
                    "action=replace."
                ),
            )

        session.flush()
        return target

    def switch_recording_target(
        self,
        session: Session,
        *,
        source: StorageTarget,
        destination: StorageTarget,
    ) -> RecordingTargetSwitchResult:
        if source.id == destination.id:
            raise ApiError(
                status_code=400,
                code="storage_target_switch_same_target",
                message="Source and destination storage targets must differ.",
            )

        for target, label in (
            (source, "source"),
            (destination, "destination"),
        ):
            if (
                target.type != "local"
                or target.role != "recording"
            ):
                raise ApiError(
                    status_code=409,
                    code="storage_target_switch_invalid",
                    message=(
                        f"The {label} target must be a local recording target."
                    ),
                )

        if not destination.enabled:
            raise ApiError(
                status_code=409,
                code="storage_target_destination_disabled",
                message="Destination recording target must be enabled.",
            )

        source_config = dict(source.config_json or {})
        destination_config = dict(
            destination.config_json or {}
        )
        source_path = source_config.get("path")
        destination_path = destination_config.get(
            "path"
        )
        if (
            not isinstance(source_path, str)
            or not isinstance(destination_path, str)
        ):
            raise ApiError(
                status_code=409,
                code="storage_target_switch_invalid",
                message="Recording target path configuration is invalid.",
            )
        if source_path == destination_path:
            raise ApiError(
                status_code=409,
                code="storage_target_switch_same_path",
                message=(
                    "Source and destination recording targets must use "
                    "different paths."
                ),
            )

        LocalStorageCapacityService.ensure_write_capacity(
            root=Path(destination_path),
            config=destination_config,
        )

        explicit_policies = list(
            session.scalars(
                select(RecordingPolicy).where(
                    RecordingPolicy.storage_target_id
                    == source.id
                )
            )
        )
        implicit_policies = list(
            session.scalars(
                select(RecordingPolicy).where(
                    RecordingPolicy.storage_target_id
                    .is_(None)
                )
            )
        )

        enabled_local = list(
            session.scalars(
                select(StorageTarget).where(
                    StorageTarget.type == "local",
                    StorageTarget.role == "recording",
                    StorageTarget.enabled.is_(True),
                )
            )
        )
        active_defaults = [
            item
            for item in enabled_local
            if bool(
                (item.config_json or {}).get(
                    "default_recording"
                )
            )
        ]
        source_is_default = any(
            item.id == source.id
            for item in active_defaults
        )
        # If no enabled default exists, implicit policies are currently
        # ambiguous once multiple local targets exist. An explicit switch
        # operation is allowed to repair that state by making the selected
        # destination the new default.
        move_default = (
            source_is_default
            or (
                not active_defaults
                and bool(implicit_policies)
            )
        )

        if (
            not explicit_policies
            and not move_default
        ):
            raise ApiError(
                status_code=409,
                code="storage_target_not_routed",
                message=(
                    "No recording policy currently routes writes through "
                    "the selected source target."
                ),
            )

        affected: set[uuid.UUID] = set()
        for policy in explicit_policies:
            policy.storage_target_id = (
                destination.id
            )
            affected.add(policy.camera_id)

        implicit_rebound = 0
        if move_default:
            source_config[
                "default_recording"
            ] = False
            destination_config[
                "default_recording"
            ] = True
            source.config_json = source_config
            destination.config_json = (
                destination_config
            )
            self._ensure_default_recording_unique(
                session,
                target_id=destination.id,
                target_type=destination.type,
                role=destination.role,
                enabled=destination.enabled,
                config=destination_config,
            )
            implicit_rebound = len(
                implicit_policies
            )
            affected.update(
                policy.camera_id
                for policy in implicit_policies
            )

        session.flush()
        return RecordingTargetSwitchResult(
            source_target_id=source.id,
            destination_target_id=destination.id,
            explicit_policies_updated=len(
                explicit_policies
            ),
            implicit_policies_rebound=(
                implicit_rebound
            ),
            default_moved=move_default,
            affected_camera_ids=tuple(
                sorted(
                    affected,
                    key=str,
                )
            ),
        )


    def delete(
        self,
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
            try:
                self.secret_store.delete(
                    session,
                    secret_id,
                    kind="rclone_config",
                    owner_type="storage_target",
                    owner_id=target.id,
                )
            except KeyError:
                pass

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
        try:
            payload = self.secret_store.read_json(
                session,
                target.credential_secret_ref,
                kind="rclone_config",
                owner_type="storage_target",
                owner_id=target.id,
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
            capacity = (
                LocalStorageCapacityService
                .inspect(
                    root=root,
                    config=config,
                )
            )
            return StorageTargetTestResult(
                type="local",
                detail="read_write_ok",
                free_bytes=capacity.free_bytes,
                total_bytes=capacity.total_bytes,
                used_bytes=capacity.used_bytes,
                used_percent=capacity.used_percent,
                capacity_level=capacity.level,
                warning_percent=(
                    capacity.watermarks
                    .warning_percent
                ),
                high_percent=(
                    capacity.watermarks
                    .high_percent
                ),
                critical_percent=(
                    capacity.watermarks
                    .critical_percent
                ),
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
