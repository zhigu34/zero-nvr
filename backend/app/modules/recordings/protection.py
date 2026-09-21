from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.cameras.models import Camera
from app.modules.recordings.models import (
    RecordingProtection,
    RecordingSegment,
)
from app.modules.storage.models import RecordingLocation


class RecordingProtectionService:
    @staticmethod
    def _utc(
        value: datetime,
        *,
        field_name: str,
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ApiError(
                status_code=422,
                code="timezone_required",
                message=f"{field_name} must include a timezone offset.",
            )
        return value.astimezone(UTC)

    @staticmethod
    def get(
        session: Session,
        protection_id: uuid.UUID,
    ) -> RecordingProtection:
        protection = session.get(
            RecordingProtection,
            protection_id,
        )
        if protection is None:
            raise ApiError(
                status_code=404,
                code="recording_protection_not_found",
                message="Recording protection was not found.",
            )
        return protection

    @staticmethod
    def list_for_camera(
        session: Session,
        *,
        camera_id: uuid.UUID,
    ) -> list[RecordingProtection]:
        return list(
            session.scalars(
                select(RecordingProtection)
                .where(
                    RecordingProtection.camera_id == camera_id
                )
                .order_by(
                    RecordingProtection.started_at.desc(),
                    RecordingProtection.id.desc(),
                )
            )
        )

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        started_at: datetime,
        ended_at: datetime,
        reason: str,
        created_by: uuid.UUID | None,
        expires_at: datetime | None,
    ) -> RecordingProtection:
        if session.get(Camera, camera_id) is None:
            raise ApiError(
                status_code=404,
                code="camera_not_found",
                message="Camera was not found.",
            )

        start = cls._utc(
            started_at,
            field_name="started_at",
        )
        end = cls._utc(
            ended_at,
            field_name="ended_at",
        )
        if end <= start:
            raise ApiError(
                status_code=400,
                code="recording_protection_range_invalid",
                message="Protection end must be after start.",
            )

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ApiError(
                status_code=400,
                code="recording_protection_reason_required",
                message="Protection reason is required.",
            )
        if len(normalized_reason) > 1024:
            raise ApiError(
                status_code=400,
                code="recording_protection_reason_too_long",
                message="Protection reason is too long.",
            )

        expiry = (
            cls._utc(
                expires_at,
                field_name="expires_at",
            )
            if expires_at is not None
            else None
        )
        if expiry is not None and expiry <= datetime.now(UTC):
            raise ApiError(
                status_code=400,
                code="recording_protection_expiry_invalid",
                message="Protection expiry must be in the future.",
            )

        deletion_in_progress = session.scalar(
            select(RecordingLocation.id)
            .join(
                RecordingSegment,
                RecordingSegment.id
                == RecordingLocation.recording_segment_id,
            )
            .where(
                RecordingLocation.state == "DELETING",
                RecordingSegment.camera_id == camera_id,
                RecordingSegment.started_at < end,
                RecordingSegment.ended_at > start,
            )
            .limit(1)
        )
        if deletion_in_progress is not None:
            raise ApiError(
                status_code=409,
                code="recording_deletion_in_progress",
                message="A recording in this range is already being deleted.",
            )

        protection = RecordingProtection(
            camera_id=camera_id,
            started_at=start,
            ended_at=end,
            reason=normalized_reason,
            created_by=created_by,
            expires_at=expiry,
        )
        session.add(protection)
        session.flush()
        return protection

    @classmethod
    def update(
        cls,
        session: Session,
        *,
        protection: RecordingProtection,
        started_at: datetime,
        ended_at: datetime,
        reason: str,
        expires_at: datetime | None,
    ) -> RecordingProtection:
        start = cls._utc(
            started_at,
            field_name="started_at",
        )
        end = cls._utc(
            ended_at,
            field_name="ended_at",
        )
        if end <= start:
            raise ApiError(
                status_code=400,
                code="recording_protection_range_invalid",
                message="Protection end must be after start.",
            )

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ApiError(
                status_code=400,
                code="recording_protection_reason_required",
                message="Protection reason is required.",
            )
        if len(normalized_reason) > 1024:
            raise ApiError(
                status_code=400,
                code="recording_protection_reason_too_long",
                message="Protection reason is too long.",
            )

        expiry = (
            cls._utc(
                expires_at,
                field_name="expires_at",
            )
            if expires_at is not None
            else None
        )
        if expiry is not None and expiry <= datetime.now(UTC):
            raise ApiError(
                status_code=400,
                code="recording_protection_expiry_invalid",
                message="Protection expiry must be in the future.",
            )

        deletion_in_progress = session.scalar(
            select(RecordingLocation.id)
            .join(
                RecordingSegment,
                RecordingSegment.id
                == RecordingLocation.recording_segment_id,
            )
            .where(
                RecordingLocation.state == "DELETING",
                RecordingSegment.camera_id == protection.camera_id,
                RecordingSegment.started_at < end,
                RecordingSegment.ended_at > start,
            )
            .limit(1)
        )
        if deletion_in_progress is not None:
            raise ApiError(
                status_code=409,
                code="recording_deletion_in_progress",
                message="A recording in this range is already being deleted.",
            )

        protection.started_at = start
        protection.ended_at = end
        protection.reason = normalized_reason
        protection.expires_at = expiry
        session.flush()
        return protection


    @staticmethod
    def delete(
        session: Session,
        *,
        protection: RecordingProtection,
    ) -> None:
        session.delete(protection)
        session.flush()
