from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.cameras.models import Camera, CameraGroup
from app.modules.recordings.models import RecordingPolicy, RetentionPolicy


class RetentionPolicyAdminService:
    @staticmethod
    def list(session: Session) -> list[RetentionPolicy]:
        return list(
            session.scalars(
                select(RetentionPolicy).order_by(
                    RetentionPolicy.name,
                    RetentionPolicy.id,
                )
            )
        )

    @staticmethod
    def get(
        session: Session,
        policy_id: uuid.UUID,
    ) -> RetentionPolicy:
        policy = session.get(RetentionPolicy, policy_id)
        if policy is None:
            raise ApiError(
                status_code=404,
                code="retention_policy_not_found",
                message="Retention policy was not found.",
            )
        return policy

    @staticmethod
    def _validate_scope(
        session: Session,
        *,
        scope_type: str,
        scope_id: uuid.UUID | None,
    ) -> None:
        if scope_type == "GLOBAL":
            if scope_id is not None:
                raise ApiError(
                    status_code=400,
                    code="retention_scope_invalid",
                    message="Global retention policy cannot have a scope id.",
                )
            return

        if scope_id is None:
            raise ApiError(
                status_code=400,
                code="retention_scope_invalid",
                message="Scoped retention policy requires a scope id.",
            )

        if scope_type == "CAMERA":
            if session.get(Camera, scope_id) is None:
                raise ApiError(
                    status_code=400,
                    code="retention_camera_unknown",
                    message="Retention camera scope does not exist.",
                )
            return

        if scope_type == "CAMERA_GROUP":
            if session.get(CameraGroup, scope_id) is None:
                raise ApiError(
                    status_code=400,
                    code="retention_camera_group_unknown",
                    message="Retention camera group scope does not exist.",
                )
            return

        raise ApiError(
            status_code=400,
            code="retention_scope_invalid",
            message="Retention scope type is invalid.",
        )

    @staticmethod
    def _ensure_scope_available(
        session: Session,
        *,
        scope_type: str,
        scope_id: uuid.UUID | None,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        statement = select(RetentionPolicy.id).where(
            RetentionPolicy.scope_type == scope_type
        )
        if scope_id is None:
            statement = statement.where(
                RetentionPolicy.scope_id.is_(None)
            )
        else:
            statement = statement.where(
                RetentionPolicy.scope_id == scope_id
            )
        if exclude_id is not None:
            statement = statement.where(
                RetentionPolicy.id != exclude_id
            )
        if session.scalar(statement.limit(1)) is not None:
            raise ApiError(
                status_code=409,
                code="retention_scope_conflict",
                message="A retention policy already exists for this scope.",
            )

    @staticmethod
    def _validate_days(
        *,
        ordinary_keep_days: int,
        event_keep_days: int,
        manual_keep_days: int,
    ) -> None:
        values = (
            ordinary_keep_days,
            event_keep_days,
            manual_keep_days,
        )
        if any(value < 0 or value > 36500 for value in values):
            raise ApiError(
                status_code=400,
                code="retention_days_invalid",
                message="Retention days must be between 0 and 36500.",
            )

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        name: str,
        scope_type: str,
        scope_id: uuid.UUID | None,
        ordinary_keep_days: int,
        event_keep_days: int,
        manual_keep_days: int,
        mode: str,
        require_archive_before_delete: bool,
        enabled: bool,
    ) -> RetentionPolicy:
        normalized_name = name.strip()
        if not normalized_name:
            raise ApiError(
                status_code=400,
                code="retention_name_invalid",
                message="Retention policy name is required.",
            )
        cls._validate_scope(
            session,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        cls._ensure_scope_available(
            session,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        cls._validate_days(
            ordinary_keep_days=ordinary_keep_days,
            event_keep_days=event_keep_days,
            manual_keep_days=manual_keep_days,
        )
        if mode not in {"BEST_EFFORT", "HARD"}:
            raise ApiError(
                status_code=400,
                code="retention_mode_invalid",
                message="Retention mode is invalid.",
            )

        existing_name = session.scalar(
            select(RetentionPolicy.id).where(
                RetentionPolicy.name == normalized_name
            )
        )
        if existing_name is not None:
            raise ApiError(
                status_code=409,
                code="retention_name_conflict",
                message="Retention policy name is already in use.",
            )

        policy = RetentionPolicy(
            name=normalized_name,
            scope_type=scope_type,
            scope_id=scope_id,
            ordinary_keep_days=ordinary_keep_days,
            event_keep_days=event_keep_days,
            manual_keep_days=manual_keep_days,
            mode=mode,
            require_archive_before_delete=require_archive_before_delete,
            enabled=enabled,
        )
        session.add(policy)
        session.flush()
        return policy

    @classmethod
    def update(
        cls,
        session: Session,
        *,
        policy: RetentionPolicy,
        changes: dict[str, object],
    ) -> RetentionPolicy:
        non_nullable = {
            "name",
            "scope_type",
            "ordinary_keep_days",
            "event_keep_days",
            "manual_keep_days",
            "mode",
            "require_archive_before_delete",
            "enabled",
        }
        if any(
            key in changes and changes[key] is None
            for key in non_nullable
        ):
            raise ApiError(
                status_code=400,
                code="retention_patch_null_invalid",
                message="Retention policy field cannot be null.",
            )

        name = str(changes.get("name", policy.name)).strip()
        if not name:
            raise ApiError(
                status_code=400,
                code="retention_name_invalid",
                message="Retention policy name is required.",
            )

        scope_type = str(
            changes.get("scope_type", policy.scope_type)
        )
        raw_scope_id = changes.get("scope_id", policy.scope_id)
        scope_id = (
            raw_scope_id
            if isinstance(raw_scope_id, uuid.UUID)
            else None
        )

        ordinary = int(
            changes.get(
                "ordinary_keep_days",
                policy.ordinary_keep_days,
            )
        )
        event = int(
            changes.get(
                "event_keep_days",
                policy.event_keep_days,
            )
        )
        manual = int(
            changes.get(
                "manual_keep_days",
                policy.manual_keep_days,
            )
        )
        mode = str(changes.get("mode", policy.mode))

        cls._validate_scope(
            session,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        cls._ensure_scope_available(
            session,
            scope_type=scope_type,
            scope_id=scope_id,
            exclude_id=policy.id,
        )
        cls._validate_days(
            ordinary_keep_days=ordinary,
            event_keep_days=event,
            manual_keep_days=manual,
        )
        if mode not in {"BEST_EFFORT", "HARD"}:
            raise ApiError(
                status_code=400,
                code="retention_mode_invalid",
                message="Retention mode is invalid.",
            )

        name_conflict = session.scalar(
            select(RetentionPolicy.id).where(
                RetentionPolicy.name == name,
                RetentionPolicy.id != policy.id,
            )
        )
        if name_conflict is not None:
            raise ApiError(
                status_code=409,
                code="retention_name_conflict",
                message="Retention policy name is already in use.",
            )

        policy.name = name
        policy.scope_type = scope_type
        policy.scope_id = scope_id
        policy.ordinary_keep_days = ordinary
        policy.event_keep_days = event
        policy.manual_keep_days = manual
        policy.mode = mode
        if "require_archive_before_delete" in changes:
            policy.require_archive_before_delete = bool(
                changes["require_archive_before_delete"]
            )
        if "enabled" in changes:
            policy.enabled = bool(changes["enabled"])

        session.flush()
        return policy

    @staticmethod
    def delete(
        session: Session,
        *,
        policy: RetentionPolicy,
    ) -> None:
        in_use = session.scalar(
            select(RecordingPolicy.id)
            .where(
                RecordingPolicy.retention_policy_id
                == policy.id
            )
            .limit(1)
        )
        if in_use is not None:
            raise ApiError(
                status_code=409,
                code="retention_policy_in_use",
                message="Retention policy is referenced by a camera recording policy.",
            )
        session.delete(policy)
        session.flush()
