from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.integrations.restic import (
    ResticAdapter,
    ResticIntegrationError,
)

from .database_snapshot import (
    DatabaseSnapshotError,
    DatabaseSnapshotService,
)
from .models import BackupPolicy, BackupSet
from .service import BackupPolicyService, ResolvedBackupPolicy


BACKUP_MANIFEST_FORMAT = "zero-nvr.backup-manifest"
BACKUP_MANIFEST_VERSION = 1


@dataclass(frozen=True, slots=True)
class BackupExecutionPlan:
    backup_set_id: uuid.UUID
    policy_id: uuid.UUID
    repository: str
    password: str
    environment: dict[str, str]
    initialize_if_missing: bool
    retention: dict[str, int]
    verify_after_backup: bool
    include_deployment_config: bool
    database_backend: str
    work_dir: Path


class BackupRunService:
    @staticmethod
    def schema_revision(database: Database) -> str:
        try:
            with database.engine.connect() as connection:
                value = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
            return str(value or "unknown")
        except Exception:
            return "unknown"

    @staticmethod
    def reserve(
        session: Session,
        *,
        policy: BackupPolicy,
        settings: Settings,
        database: Database,
        reason: str,
        schedule_slot: str | None = None,
    ) -> tuple[BackupSet, bool]:
        if not policy.enabled and reason != "manual":
            raise ApiError(
                status_code=409,
                code="backup_policy_disabled",
                message="Backup policy is disabled.",
            )
        if policy.database_backend != database.url.get_backend_name():
            raise ApiError(
                status_code=409,
                code="backup_database_backend_mismatch",
                message="Backup policy database backend does not match the active database.",
            )

        if schedule_slot is not None:
            existing = session.scalar(
                select(BackupSet).where(
                    BackupSet.backup_policy_id == policy.id,
                    BackupSet.schedule_slot == schedule_slot,
                )
            )
            if existing is not None:
                return existing, False

        backup_set = BackupSet(
            backup_policy_id=policy.id,
            state="PENDING",
            reason=reason,
            schedule_slot=schedule_slot,
            app_version=settings.app_version,
            schema_revision=BackupRunService.schema_revision(
                database
            ),
            database_engine=database.url.get_backend_name(),
            verification_state=(
                "PENDING"
                if policy.verify_after_backup
                else "SKIPPED"
            ),
        )
        session.add(backup_set)
        try:
            with session.begin_nested():
                session.flush()
        except IntegrityError:
            if schedule_slot is None:
                raise
            existing = session.scalar(
                select(BackupSet).where(
                    BackupSet.backup_policy_id == policy.id,
                    BackupSet.schedule_slot == schedule_slot,
                )
            )
            if existing is None:
                raise
            return existing, False
        return backup_set, True


class BackupExecutionService:
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self.settings = settings

    def _safe_work_dir(self, backup_set_id: uuid.UUID) -> Path:
        root = (self.settings.cache_dir / "backups").resolve(strict=False)
        work = (root / str(backup_set_id)).resolve(strict=False)
        try:
            work.relative_to(root)
        except ValueError as exc:
            raise DatabaseSnapshotError(
                "backup_work_dir_invalid",
                "Backup staging directory is invalid.",
            ) from exc
        return work

    def _safe_deployment_config(self) -> Path:
        configured = self.settings.deployment_config_dir
        if configured is None:
            raise DatabaseSnapshotError(
                "backup_deployment_config_unavailable",
                "Deployment configuration backup was requested but no deployment config directory is mounted.",
            )
        root = configured.resolve()
        if not root.is_dir():
            raise DatabaseSnapshotError(
                "backup_deployment_config_unavailable",
                "Deployment configuration directory is unavailable.",
            )

        forbidden = [
            self.settings.recordings_dir.resolve(strict=False),
            self.settings.prebuffer_dir.resolve(strict=False),
            self.settings.cache_dir.resolve(strict=False),
            self.settings.data_dir.resolve(strict=False),
        ]
        for value in forbidden:
            if root == value or value.is_relative_to(root):
                raise DatabaseSnapshotError(
                    "backup_deployment_config_unsafe",
                    "Deployment configuration directory would include runtime or recording data.",
                )
        return root

    def prepare(
        self,
        database: Database,
        *,
        backup_set_id: uuid.UUID,
    ) -> BackupExecutionPlan | None:
        with database.session() as session:
            backup_set = session.get(
                BackupSet,
                backup_set_id,
            )
            if backup_set is None:
                raise ApiError(
                    status_code=404,
                    code="backup_not_found",
                    message="Backup set was not found.",
                )
            if backup_set.state == "COMPLETED":
                session.commit()
                return None

            policy = session.get(
                BackupPolicy,
                backup_set.backup_policy_id,
            )
            if policy is None:
                backup_set.state = "FAILED"
                backup_set.error_code = "backup_policy_missing"
                backup_set.sanitized_error = (
                    "Backup policy is unavailable."
                )
                backup_set.completed_at = utc_now()
                session.commit()
                return None

            resolved: ResolvedBackupPolicy = (
                BackupPolicyService(
                    self.settings
                ).resolve(
                    session,
                    policy=policy,
                )
            )
            backup_set.state = "RUNNING"
            backup_set.started_at = utc_now()
            backup_set.completed_at = None
            backup_set.error_code = None
            backup_set.sanitized_error = None
            plan = BackupExecutionPlan(
                backup_set_id=backup_set.id,
                policy_id=policy.id,
                repository=resolved.repository,
                password=resolved.password,
                environment=resolved.environment,
                initialize_if_missing=(
                    resolved.initialize_if_missing
                ),
                retention=resolved.retention,
                verify_after_backup=(
                    policy.verify_after_backup
                ),
                include_deployment_config=(
                    policy.include_deployment_config
                ),
                database_backend=policy.database_backend,
                work_dir=self._safe_work_dir(
                    backup_set.id
                ),
            )
            session.commit()
            return plan

    @staticmethod
    def _manifest(
        *,
        plan: BackupExecutionPlan,
        database: Database,
        settings: Settings,
        snapshot_path: Path,
    ) -> Path:
        path = plan.work_dir / "manifest.json"
        with database.session() as session:
            secret_store_key_ids = sorted(
                SecretStore(
                    settings
                ).record_key_ids(session)
            )
        payload = {
            "format": BACKUP_MANIFEST_FORMAT,
            "format_version": BACKUP_MANIFEST_VERSION,
            "backup_set_id": str(plan.backup_set_id),
            "policy_id": str(plan.policy_id),
            "created_at": datetime.now(UTC).isoformat(),
            "app_version": settings.app_version,
            "schema_revision": BackupRunService.schema_revision(
                database
            ),
            "database_engine": database.url.get_backend_name(),
            "database_snapshot": snapshot_path.name,
            "recordings_included": False,
            "recovery_kit_required": True,
            "secret_store_key_ids": secret_store_key_ids,
        }
        path.write_text(
            json.dumps(
                payload,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _mark_failed(
        database: Database,
        *,
        backup_set_id: uuid.UUID,
        code: str,
        message: str,
    ) -> None:
        with database.session() as session:
            item = session.get(BackupSet, backup_set_id)
            if item is not None:
                item.state = "FAILED"
                item.error_code = code
                item.sanitized_error = message[:1024]
                item.completed_at = utc_now()
                if item.verification_state == "PENDING":
                    item.verification_state = "SKIPPED"
                session.commit()

    @staticmethod
    def _complete(
        database: Database,
        *,
        backup_set_id: uuid.UUID,
        snapshot_id: str,
        size_bytes: int | None,
        verification_state: str,
        post_error_code: str | None = None,
        post_error: str | None = None,
    ) -> None:
        with database.session() as session:
            item = session.get(BackupSet, backup_set_id)
            if item is None:
                return
            item.state = "COMPLETED"
            item.restic_snapshot_id = snapshot_id
            item.size_bytes = size_bytes
            item.verification_state = verification_state
            item.last_verified_at = (
                utc_now()
                if verification_state
                in {"PASSED", "FAILED"}
                else None
            )
            item.error_code = post_error_code
            item.sanitized_error = (
                post_error[:1024]
                if post_error is not None
                else None
            )
            item.completed_at = utc_now()
            session.commit()

    def execute(
        self,
        database: Database,
        *,
        backup_set_id: uuid.UUID,
    ) -> str:
        plan = self.prepare(
            database,
            backup_set_id=backup_set_id,
        )
        if plan is None:
            with database.session() as session:
                item = session.get(
                    BackupSet,
                    backup_set_id,
                )
                return (
                    item.state
                    if item is not None
                    else "FAILED"
                )

        shutil.rmtree(
            plan.work_dir,
            ignore_errors=True,
        )
        plan.work_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        snapshot_id: str | None = None

        try:
            snapshot = DatabaseSnapshotService(
                self.settings
            ).snapshot(
                database,
                destination_dir=plan.work_dir,
            )
            manifest = self._manifest(
                plan=plan,
                database=database,
                settings=self.settings,
                snapshot_path=snapshot.path,
            )

            payload_paths = [
                snapshot.path,
                manifest,
            ]
            if plan.include_deployment_config:
                payload_paths.append(
                    self._safe_deployment_config()
                )

            restic = ResticAdapter(
                repository=plan.repository,
                password=plan.password,
                environment=plan.environment,
                binary=self.settings.restic_binary,
                timeout_seconds=(
                    self.settings.restic_timeout_seconds
                ),
            )
            restic.ensure_repository(
                initialize_if_missing=(
                    plan.initialize_if_missing
                )
            )
            backup_tag = f"backup-set:{plan.backup_set_id}"
            result = restic.latest_snapshot_for_tag(
                backup_tag
            )
            if result is None:
                result = restic.backup(
                    paths=payload_paths,
                    tags=[
                        "zero-nvr",
                        backup_tag,
                    ],
                )
            snapshot_id = result.snapshot_id

            verification_state = "SKIPPED"
            post_code: str | None = None
            post_error: str | None = None
            if plan.verify_after_backup:
                try:
                    restic.verify_snapshot(
                        result.snapshot_id
                    )
                    restic.check()
                    verification_state = "PASSED"
                except ResticIntegrationError:
                    verification_state = "FAILED"
                    post_code = "restic_check_failed"
                    post_error = (
                        "Backup snapshot was created but repository verification failed."
                    )

            if plan.retention:
                try:
                    restic.forget(plan.retention)
                except ResticIntegrationError:
                    if post_code is None:
                        post_code = "restic_retention_failed"
                        post_error = (
                            "Backup snapshot was created but retention cleanup failed."
                        )

            self._complete(
                database,
                backup_set_id=plan.backup_set_id,
                snapshot_id=result.snapshot_id,
                size_bytes=result.size_bytes,
                verification_state=verification_state,
                post_error_code=post_code,
                post_error=post_error,
            )
            return "COMPLETED"
        except DatabaseSnapshotError as exc:
            self._mark_failed(
                database,
                backup_set_id=plan.backup_set_id,
                code=exc.code,
                message=str(exc),
            )
            return "FAILED"
        except ResticIntegrationError as exc:
            # If a snapshot id has already been obtained, never retry the
            # backup blindly and create duplicate snapshots.
            if snapshot_id is not None:
                self._complete(
                    database,
                    backup_set_id=plan.backup_set_id,
                    snapshot_id=snapshot_id,
                    size_bytes=None,
                    verification_state="FAILED",
                    post_error_code=exc.code,
                    post_error=str(exc),
                )
                return "COMPLETED"
            self._mark_failed(
                database,
                backup_set_id=plan.backup_set_id,
                code=exc.code,
                message=str(exc),
            )
            return "FAILED"
        finally:
            shutil.rmtree(
                plan.work_dir,
                ignore_errors=True,
            )

    def verify(
        self,
        database: Database,
        *,
        backup_set_id: uuid.UUID,
    ) -> str:
        with database.session() as session:
            item = session.get(BackupSet, backup_set_id)
            if item is None:
                raise ApiError(
                    status_code=404,
                    code="backup_not_found",
                    message="Backup set was not found.",
                )
            policy = session.get(
                BackupPolicy,
                item.backup_policy_id,
            )
            if (
                policy is None
                or item.restic_snapshot_id is None
            ):
                raise ApiError(
                    status_code=409,
                    code="backup_not_verifiable",
                    message="Backup set cannot be verified.",
                )
            resolved = BackupPolicyService(
                self.settings
            ).resolve(
                session,
                policy=policy,
            )
            item.verification_state = "PENDING"
            session.commit()

        try:
            restic = ResticAdapter(
                repository=resolved.repository,
                password=resolved.password,
                environment=resolved.environment,
                binary=self.settings.restic_binary,
                timeout_seconds=self.settings.restic_timeout_seconds,
            )
            restic.verify_snapshot(
                item.restic_snapshot_id
            )
            restic.check()
        except ResticIntegrationError as exc:
            with database.session() as session:
                item = session.get(
                    BackupSet,
                    backup_set_id,
                )
                if item is not None:
                    item.verification_state = "FAILED"
                    item.last_verified_at = utc_now()
                    item.error_code = exc.code
                    item.sanitized_error = str(exc)[:1024]
                    session.commit()
            return "FAILED"

        with database.session() as session:
            item = session.get(
                BackupSet,
                backup_set_id,
            )
            if item is not None:
                item.verification_state = "PASSED"
                item.last_verified_at = utc_now()
                if item.state == "COMPLETED":
                    item.error_code = None
                    item.sanitized_error = None
                session.commit()
        return "PASSED"
