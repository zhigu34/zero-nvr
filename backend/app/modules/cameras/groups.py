from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError

from .models import (
    Camera,
    CameraGroup,
    CameraGroupMember,
    PrincipalCameraScopeEntry,
)


class CameraGroupService:
    @staticmethod
    def list(session: Session) -> list[CameraGroup]:
        return list(
            session.scalars(
                select(CameraGroup).order_by(
                    CameraGroup.name,
                    CameraGroup.id,
                )
            )
        )

    @staticmethod
    def get(
        session: Session,
        group_id: uuid.UUID,
    ) -> CameraGroup:
        group = session.get(CameraGroup, group_id)
        if group is None:
            raise ApiError(
                status_code=404,
                code="camera_group_not_found",
                message="Camera group was not found.",
            )
        return group

    @staticmethod
    def camera_ids(
        session: Session,
        group_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        return list(
            session.scalars(
                select(CameraGroupMember.camera_id)
                .where(
                    CameraGroupMember.camera_group_id
                    == group_id
                )
                .order_by(CameraGroupMember.camera_id)
            )
        )

    @classmethod
    def _validate_parent(
        cls,
        session: Session,
        *,
        parent_id: uuid.UUID | None,
        group_id: uuid.UUID | None = None,
    ) -> None:
        if parent_id is None:
            return
        if group_id is not None and parent_id == group_id:
            raise ApiError(
                status_code=400,
                code="camera_group_parent_cycle",
                message="Camera group cannot be its own parent.",
            )

        parent = session.get(CameraGroup, parent_id)
        if parent is None:
            raise ApiError(
                status_code=400,
                code="camera_group_parent_invalid",
                message="Camera group parent does not exist.",
            )

        seen: set[uuid.UUID] = set()
        current: CameraGroup | None = parent
        while current is not None:
            if current.id in seen:
                raise ApiError(
                    status_code=409,
                    code="camera_group_hierarchy_invalid",
                    message="Camera group hierarchy contains a cycle.",
                )
            seen.add(current.id)
            if group_id is not None and current.id == group_id:
                raise ApiError(
                    status_code=400,
                    code="camera_group_parent_cycle",
                    message="Camera group hierarchy cannot contain a cycle.",
                )
            if current.parent_id is None:
                break
            current = session.get(
                CameraGroup,
                current.parent_id,
            )

    @staticmethod
    def _validate_camera_ids(
        session: Session,
        camera_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        normalized = sorted(set(camera_ids), key=str)
        if not normalized:
            return []

        found = set(
            session.scalars(
                select(Camera.id).where(
                    Camera.id.in_(normalized)
                )
            )
        )
        missing = set(normalized) - found
        if missing:
            raise ApiError(
                status_code=400,
                code="camera_group_camera_invalid",
                message="Camera group references an unknown camera.",
                details={
                    "camera_ids": sorted(
                        str(item) for item in missing
                    )
                },
            )
        return normalized

    @classmethod
    def _replace_members(
        cls,
        session: Session,
        *,
        group_id: uuid.UUID,
        camera_ids: list[uuid.UUID],
    ) -> None:
        normalized = cls._validate_camera_ids(
            session,
            camera_ids,
        )
        session.execute(
            delete(CameraGroupMember).where(
                CameraGroupMember.camera_group_id
                == group_id
            )
        )
        session.add_all(
            [
                CameraGroupMember(
                    camera_group_id=group_id,
                    camera_id=camera_id,
                )
                for camera_id in normalized
            ]
        )
        session.flush()

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        name: str,
        description: str | None,
        parent_id: uuid.UUID | None,
        camera_ids: list[uuid.UUID],
    ) -> CameraGroup:
        normalized_name = name.strip()
        if not normalized_name:
            raise ApiError(
                status_code=400,
                code="camera_group_name_invalid",
                message="Camera group name is invalid.",
            )
        cls._validate_parent(
            session,
            parent_id=parent_id,
        )

        group = CameraGroup(
            name=normalized_name,
            description=(
                description.strip()
                if description is not None
                and description.strip()
                else None
            ),
            parent_id=parent_id,
        )
        session.add(group)
        try:
            session.flush()
            cls._replace_members(
                session,
                group_id=group.id,
                camera_ids=camera_ids,
            )
        except IntegrityError as exc:
            raise ApiError(
                status_code=409,
                code="camera_group_name_conflict",
                message="Camera group name is already in use.",
            ) from exc
        return group

    @classmethod
    def update(
        cls,
        session: Session,
        *,
        group: CameraGroup,
        changes: dict[str, object],
    ) -> CameraGroup:
        if "name" in changes:
            raw_name = changes["name"]
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise ApiError(
                    status_code=400,
                    code="camera_group_name_invalid",
                    message="Camera group name is invalid.",
                )
            group.name = raw_name.strip()

        if "description" in changes:
            raw_description = changes["description"]
            group.description = (
                str(raw_description).strip()
                if raw_description is not None
                and str(raw_description).strip()
                else None
            )

        if "parent_id" in changes:
            raw_parent = changes["parent_id"]
            parent_id = (
                uuid.UUID(str(raw_parent))
                if raw_parent is not None
                else None
            )
            cls._validate_parent(
                session,
                parent_id=parent_id,
                group_id=group.id,
            )
            group.parent_id = parent_id

        try:
            session.flush()
        except IntegrityError as exc:
            raise ApiError(
                status_code=409,
                code="camera_group_name_conflict",
                message="Camera group name is already in use.",
            ) from exc

        if "camera_ids" in changes:
            raw_camera_ids = changes["camera_ids"]
            if not isinstance(raw_camera_ids, list):
                raise ApiError(
                    status_code=400,
                    code="camera_group_camera_invalid",
                    message="Camera group camera list is invalid.",
                )
            cls._replace_members(
                session,
                group_id=group.id,
                camera_ids=[
                    uuid.UUID(str(item))
                    for item in raw_camera_ids
                ],
            )

        session.flush()
        return group

    @classmethod
    def delete(
        cls,
        session: Session,
        *,
        group: CameraGroup,
    ) -> None:
        child_id = session.scalar(
            select(CameraGroup.id)
            .where(CameraGroup.parent_id == group.id)
            .limit(1)
        )
        if child_id is not None:
            raise ApiError(
                status_code=409,
                code="camera_group_has_children",
                message="Camera group with child groups cannot be deleted.",
            )

        scope_entry_id = session.scalar(
            select(PrincipalCameraScopeEntry.id)
            .where(
                PrincipalCameraScopeEntry.camera_group_id
                == group.id
            )
            .limit(1)
        )
        if scope_entry_id is not None:
            raise ApiError(
                status_code=409,
                code="camera_group_in_use",
                message="Camera group is referenced by an access scope.",
            )

        session.delete(group)
        session.flush()
