from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore

from .models import BackupPolicy


_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_RESERVED_ENV = {
    "RESTIC_REPOSITORY",
    "RESTIC_PASSWORD",
    "RESTIC_PASSWORD_FILE",
}


@dataclass(frozen=True, slots=True)
class ResolvedBackupPolicy:
    policy_id: uuid.UUID
    repository: str
    password: str
    environment: dict[str, str]
    initialize_if_missing: bool
    retention: dict[str, int]


class BackupPolicyService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.secret_store = SecretStore(settings)

    @staticmethod
    def normalize_schedule(
        value: dict[str, object],
    ) -> dict[str, object]:
        if not value:
            return {}
        if set(value) != {"cron", "timezone"}:
            raise ApiError(
                status_code=400,
                code="backup_schedule_invalid",
                message="Backup schedule must contain cron and timezone.",
            )
        cron = value.get("cron")
        timezone = value.get("timezone")
        if (
            not isinstance(cron, str)
            or not cron.strip()
            or len(cron) > 128
            or not isinstance(timezone, str)
            or not timezone.strip()
        ):
            raise ApiError(
                status_code=400,
                code="backup_schedule_invalid",
                message="Backup schedule is invalid.",
            )
        # V1 intentionally supports five-field minute-level cron only.
        fields = cron.strip().split()
        if len(fields) != 5 or not croniter.is_valid(cron.strip()):
            raise ApiError(
                status_code=400,
                code="backup_schedule_invalid",
                message="Backup schedule must be a valid five-field cron expression.",
            )
        try:
            ZoneInfo(timezone.strip())
        except ZoneInfoNotFoundError as exc:
            raise ApiError(
                status_code=400,
                code="backup_schedule_timezone_invalid",
                message="Backup schedule timezone is invalid.",
            ) from exc
        return {
            "cron": cron.strip(),
            "timezone": timezone.strip(),
        }

    @staticmethod
    def normalize_retention(
        value: dict[str, object],
    ) -> dict[str, int]:
        allowed = {
            "keep_last",
            "keep_daily",
            "keep_weekly",
            "keep_monthly",
            "keep_yearly",
        }
        if set(value) - allowed:
            raise ApiError(
                status_code=400,
                code="backup_retention_invalid",
                message="Backup retention contains unsupported fields.",
            )
        normalized: dict[str, int] = {}
        for key, raw in value.items():
            if (
                isinstance(raw, bool)
                or not isinstance(raw, int)
                or raw < 0
                or raw > 10000
            ):
                raise ApiError(
                    status_code=400,
                    code="backup_retention_invalid",
                    message="Backup retention value is invalid.",
                )
            normalized[key] = raw
        return normalized

    @staticmethod
    def normalize_repository(
        repository: str,
    ) -> str:
        value = repository.strip()
        if (
            not value
            or len(value) > 4096
            or "\n" in value
            or "\r" in value
            or "\x00" in value
        ):
            raise ApiError(
                status_code=400,
                code="backup_repository_invalid",
                message="Backup repository is invalid.",
            )
        if "://" in value:
            try:
                parsed = urlsplit(value)
            except ValueError as exc:
                raise ApiError(
                    status_code=400,
                    code="backup_repository_invalid",
                    message="Backup repository is invalid.",
                ) from exc
            if parsed.username is not None or parsed.password is not None:
                raise ApiError(
                    status_code=400,
                    code="backup_repository_credentials_embedded",
                    message="Repository credentials must be configured separately.",
                )
        return value

    @staticmethod
    def normalize_environment(
        environment: dict[str, str],
    ) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, raw in environment.items():
            name = key.strip()
            if (
                not _ENV_KEY.fullmatch(name)
                or name in _RESERVED_ENV
                or not isinstance(raw, str)
                or "\x00" in raw
                or len(raw) > 8192
            ):
                raise ApiError(
                    status_code=400,
                    code="backup_credentials_invalid",
                    message="Backup credential environment is invalid.",
                )
            normalized[name] = raw
        return normalized

    @staticmethod
    def list(session: Session) -> list[BackupPolicy]:
        return list(
            session.scalars(
                select(BackupPolicy).order_by(
                    BackupPolicy.name,
                    BackupPolicy.id,
                )
            )
        )

    @staticmethod
    def get(
        session: Session,
        policy_id: uuid.UUID,
    ) -> BackupPolicy:
        policy = session.get(BackupPolicy, policy_id)
        if policy is None:
            raise ApiError(
                status_code=404,
                code="backup_policy_not_found",
                message="Backup policy was not found.",
            )
        return policy

    @staticmethod
    def _ensure_name(
        session: Session,
        *,
        name: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        statement = select(BackupPolicy.id).where(
            BackupPolicy.name == name
        )
        if exclude_id is not None:
            statement = statement.where(
                BackupPolicy.id != exclude_id
            )
        if session.scalar(statement.limit(1)) is not None:
            raise ApiError(
                status_code=409,
                code="backup_policy_name_conflict",
                message="Backup policy name is already in use.",
            )

    def create(
        self,
        session: Session,
        *,
        name: str,
        enabled: bool,
        repository: str,
        password: str,
        environment: dict[str, str],
        initialize_if_missing: bool,
        database_backend: str,
        schedule: dict[str, object],
        retention: dict[str, object],
        verify_after_backup: bool,
        repository_check_schedule: dict[str, object],
        include_deployment_config: bool,
    ) -> BackupPolicy:
        normalized_name = name.strip()
        if not normalized_name:
            raise ApiError(
                status_code=400,
                code="backup_policy_name_invalid",
                message="Backup policy name is invalid.",
            )
        self._ensure_name(session, name=normalized_name)

        if database_backend not in {"sqlite", "postgresql"}:
            raise ApiError(
                status_code=400,
                code="backup_database_backend_invalid",
                message="Backup database backend is invalid.",
            )
        repository_value = self.normalize_repository(repository)
        if not password:
            raise ApiError(
                status_code=400,
                code="backup_password_required",
                message="restic repository password is required.",
            )
        credentials = self.normalize_environment(environment)
        schedule_value = self.normalize_schedule(schedule)
        check_schedule = self.normalize_schedule(
            repository_check_schedule
        )
        retention_value = self.normalize_retention(retention)

        policy_id = uuid.uuid4()
        repository_secret_id = (
            self.secret_store.create_json(
                session,
                kind="backup_repository",
                owner_type="backup_policy",
                owner_id=policy_id,
                value={
                    "repository": repository_value,
                    "initialize_if_missing": bool(
                        initialize_if_missing
                    ),
                },
            )
        )
        credential_secret_id = (
            self.secret_store.create_json(
                session,
                kind="backup_credentials",
                owner_type="backup_policy",
                owner_id=policy_id,
                value={
                    "password": password,
                    "environment": credentials,
                },
            )
        )
        policy = BackupPolicy(
            id=policy_id,
            name=normalized_name,
            enabled=enabled,
            repository_config_ref=repository_secret_id,
            credential_secret_ref=credential_secret_id,
            database_backend=database_backend,
            schedule_json=schedule_value,
            retention_policy_json=retention_value,
            verify_after_backup=verify_after_backup,
            repository_check_schedule_json=check_schedule,
            include_deployment_config=(
                include_deployment_config
            ),
        )
        session.add(policy)
        session.flush()
        return policy

    def _replace_secret(
        self,
        session: Session,
        *,
        policy: BackupPolicy,
        secret_id: uuid.UUID,
        kind: str,
        value: dict[str, object],
    ) -> None:
        try:
            self.secret_store.replace_json(
                session,
                secret_id,
                kind=kind,
                owner_type="backup_policy",
                owner_id=policy.id,
                value=value,
            )
        except Exception as exc:
            raise ApiError(
                status_code=409,
                code="backup_secret_unavailable",
                message="Backup policy secret is unavailable.",
            ) from exc

    def update(
        self,
        session: Session,
        *,
        policy: BackupPolicy,
        changes: dict[str, object],
    ) -> BackupPolicy:
        if "name" in changes:
            raw_name = changes["name"]
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise ApiError(
                    status_code=400,
                    code="backup_policy_name_invalid",
                    message="Backup policy name is invalid.",
                )
            name = raw_name.strip()
            self._ensure_name(
                session,
                name=name,
                exclude_id=policy.id,
            )
            policy.name = name

        if "enabled" in changes:
            policy.enabled = bool(changes["enabled"])
        if "schedule" in changes:
            raw = changes["schedule"]
            if not isinstance(raw, dict):
                raise ApiError(
                    status_code=400,
                    code="backup_schedule_invalid",
                    message="Backup schedule is invalid.",
                )
            policy.schedule_json = self.normalize_schedule(raw)
        if "retention" in changes:
            raw = changes["retention"]
            if not isinstance(raw, dict):
                raise ApiError(
                    status_code=400,
                    code="backup_retention_invalid",
                    message="Backup retention is invalid.",
                )
            policy.retention_policy_json = self.normalize_retention(raw)
        if "verify_after_backup" in changes:
            policy.verify_after_backup = bool(
                changes["verify_after_backup"]
            )
        if "repository_check_schedule" in changes:
            raw = changes["repository_check_schedule"]
            if not isinstance(raw, dict):
                raise ApiError(
                    status_code=400,
                    code="backup_schedule_invalid",
                    message="Repository check schedule is invalid.",
                )
            policy.repository_check_schedule_json = (
                self.normalize_schedule(raw)
            )
        if "include_deployment_config" in changes:
            policy.include_deployment_config = bool(
                changes["include_deployment_config"]
            )

        if (
            "repository" in changes
            or "initialize_if_missing" in changes
        ):
            current = self._decrypt(
                session,
                policy=policy,
                secret_id=policy.repository_config_ref,
                kind="backup_repository",
            )
            repository = changes.get(
                "repository",
                current.get("repository"),
            )
            initialize = changes.get(
                "initialize_if_missing",
                current.get("initialize_if_missing", False),
            )
            if not isinstance(repository, str):
                raise ApiError(
                    status_code=400,
                    code="backup_repository_invalid",
                    message="Backup repository is invalid.",
                )
            self._replace_secret(
                session,
                policy=policy,
                secret_id=policy.repository_config_ref,
                kind="backup_repository",
                value={
                    "repository": self.normalize_repository(
                        repository
                    ),
                    "initialize_if_missing": bool(
                        initialize
                    ),
                },
            )

        if "credentials" in changes:
            raw = changes["credentials"]
            if not isinstance(raw, dict):
                raise ApiError(
                    status_code=400,
                    code="backup_credentials_invalid",
                    message="Backup credentials are invalid.",
                )

            current_credentials: dict[str, object] = {}
            if policy.credential_secret_ref is not None:
                current_credentials = self._decrypt(
                    session,
                    policy=policy,
                    secret_id=policy.credential_secret_ref,
                    kind="backup_credentials",
                )

            password = raw.get(
                "password",
                current_credentials.get("password"),
            )
            environment = raw.get(
                "environment",
                current_credentials.get("environment", {}),
            )
            if (
                not isinstance(password, str)
                or not password
                or not isinstance(environment, dict)
                or not all(
                    isinstance(key, str)
                    and isinstance(value, str)
                    for key, value in environment.items()
                )
            ):
                raise ApiError(
                    status_code=400,
                    code="backup_credentials_invalid",
                    message="Backup credentials are invalid.",
                )
            if policy.credential_secret_ref is None:
                policy.credential_secret_ref = (
                    self.secret_store.create_json(
                        session,
                        kind="backup_credentials",
                        owner_type="backup_policy",
                        owner_id=policy.id,
                        value={
                            "password": password,
                            "environment": self.normalize_environment(
                                dict(environment)
                            ),
                        },
                    )
                )
            else:
                self._replace_secret(
                    session,
                    policy=policy,
                    secret_id=policy.credential_secret_ref,
                    kind="backup_credentials",
                    value={
                        "password": password,
                        "environment": self.normalize_environment(
                            dict(environment)
                        ),
                    },
                )

        session.flush()
        return policy

    def _decrypt(
        self,
        session: Session,
        *,
        policy: BackupPolicy,
        secret_id: uuid.UUID | None,
        kind: str,
    ) -> dict[str, object]:
        if secret_id is None:
            raise ApiError(
                status_code=409,
                code="backup_secret_unavailable",
                message="Backup policy secret is unavailable.",
            )
        try:
            return self.secret_store.read_json(
                session,
                secret_id,
                kind=kind,
                owner_type="backup_policy",
                owner_id=policy.id,
            )
        except Exception as exc:
            raise ApiError(
                status_code=409,
                code="backup_secret_unavailable",
                message="Backup policy secret could not be decrypted.",
            ) from exc

    def resolve(
        self,
        session: Session,
        *,
        policy: BackupPolicy,
    ) -> ResolvedBackupPolicy:
        repository = self._decrypt(
            session,
            policy=policy,
            secret_id=policy.repository_config_ref,
            kind="backup_repository",
        )
        credentials = self._decrypt(
            session,
            policy=policy,
            secret_id=policy.credential_secret_ref,
            kind="backup_credentials",
        )
        raw_repo = repository.get("repository")
        raw_password = credentials.get("password")
        raw_environment = credentials.get("environment", {})
        if (
            not isinstance(raw_repo, str)
            or not raw_repo
            or not isinstance(raw_password, str)
            or not raw_password
            or not isinstance(raw_environment, dict)
            or not all(
                isinstance(key, str)
                and isinstance(value, str)
                for key, value in raw_environment.items()
            )
        ):
            raise ApiError(
                status_code=409,
                code="backup_secret_unavailable",
                message="Backup policy secret is invalid.",
            )
        return ResolvedBackupPolicy(
            policy_id=policy.id,
            repository=raw_repo,
            password=raw_password,
            environment=dict(raw_environment),
            initialize_if_missing=bool(
                repository.get(
                    "initialize_if_missing",
                    False,
                )
            ),
            retention=dict(
                policy.retention_policy_json or {}
            ),
        )

    @staticmethod
    def schedule_value_matches(
        schedule: dict[str, object],
        *,
        at: datetime,
    ) -> bool:
        if not schedule:
            return False
        timezone = str(schedule["timezone"])
        cron = str(schedule["cron"])
        local = at.astimezone(ZoneInfo(timezone))
        return croniter.match(cron, local)

    @classmethod
    def schedule_matches(
        cls,
        policy: BackupPolicy,
        *,
        at: datetime,
    ) -> bool:
        if not policy.enabled:
            return False
        return cls.schedule_value_matches(
            policy.schedule_json or {},
            at=at,
        )

    @staticmethod
    def schedule_slot(
        *,
        at: datetime,
    ) -> str:
        return (
            at.astimezone(UTC)
            .replace(second=0, microsecond=0)
            .isoformat()
        )
