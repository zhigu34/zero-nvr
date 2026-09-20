from __future__ import annotations

from dataclasses import dataclass
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.cameras.models import (
    Camera,
    CameraGroup,
    CameraGroupMember,
    PrincipalCameraScope,
    PrincipalCameraScopeEntry,
)


@dataclass(frozen=True, slots=True)
class EffectiveCameraScope:
    all_cameras: bool
    camera_ids: frozenset[uuid.UUID]

    def allows(self, camera_id: uuid.UUID) -> bool:
        return self.all_cameras or camera_id in self.camera_ids


@dataclass(frozen=True, slots=True)
class CameraScopeValue:
    mode: str
    camera_ids: tuple[uuid.UUID, ...]
    camera_group_ids: tuple[uuid.UUID, ...]


class CameraScopeService:
    @staticmethod
    def ensure_scope(
        session: Session,
        *,
        principal_type: str,
        principal_id: uuid.UUID,
        mode: str,
    ) -> PrincipalCameraScope:
        scope = session.scalar(
            select(PrincipalCameraScope).where(
                PrincipalCameraScope.principal_type == principal_type,
                PrincipalCameraScope.principal_id == principal_id,
            )
        )
        if scope is None:
            scope = PrincipalCameraScope(
                principal_type=principal_type,
                principal_id=principal_id,
                scope_mode=mode,
            )
            session.add(scope)
            session.flush()
        return scope

    @staticmethod
    def get_scope(
        session: Session,
        *,
        principal_type: str,
        principal_id: uuid.UUID,
    ) -> CameraScopeValue | None:
        scope = session.scalar(
            select(PrincipalCameraScope).where(
                PrincipalCameraScope.principal_type == principal_type,
                PrincipalCameraScope.principal_id == principal_id,
            )
        )
        if scope is None:
            return None

        entries = list(
            session.scalars(
                select(PrincipalCameraScopeEntry).where(
                    PrincipalCameraScopeEntry.scope_id == scope.id
                )
            )
        )
        return CameraScopeValue(
            mode=scope.scope_mode,
            camera_ids=tuple(
                sorted(
                    (item.camera_id for item in entries if item.camera_id),
                    key=str,
                )
            ),
            camera_group_ids=tuple(
                sorted(
                    (
                        item.camera_group_id
                        for item in entries
                        if item.camera_group_id
                    ),
                    key=str,
                )
            ),
        )

    @classmethod
    def set_scope(
        cls,
        session: Session,
        *,
        principal_type: str,
        principal_id: uuid.UUID,
        mode: str,
        camera_ids: list[uuid.UUID],
        camera_group_ids: list[uuid.UUID],
    ) -> CameraScopeValue:
        if mode not in {"all", "selected", "none"}:
            raise ApiError(
                status_code=400,
                code="invalid_camera_scope_mode",
                message="Camera scope mode must be all, selected, or none.",
            )

        unique_camera_ids = set(camera_ids)
        unique_group_ids = set(camera_group_ids)

        if mode != "selected" and (unique_camera_ids or unique_group_ids):
            raise ApiError(
                status_code=400,
                code="camera_scope_entries_not_allowed",
                message="Camera/group entries are allowed only for selected scope.",
            )

        if unique_camera_ids:
            found = set(
                session.scalars(
                    select(Camera.id).where(Camera.id.in_(unique_camera_ids))
                )
            )
            missing = unique_camera_ids - found
            if missing:
                raise ApiError(
                    status_code=400,
                    code="invalid_camera_ids",
                    message="One or more cameras do not exist.",
                    details={"camera_ids": sorted(str(item) for item in missing)},
                )

        if unique_group_ids:
            found = set(
                session.scalars(
                    select(CameraGroup.id).where(
                        CameraGroup.id.in_(unique_group_ids)
                    )
                )
            )
            missing = unique_group_ids - found
            if missing:
                raise ApiError(
                    status_code=400,
                    code="invalid_camera_group_ids",
                    message="One or more camera groups do not exist.",
                    details={
                        "camera_group_ids": sorted(str(item) for item in missing)
                    },
                )

        scope = cls.ensure_scope(
            session,
            principal_type=principal_type,
            principal_id=principal_id,
            mode=mode,
        )
        scope.scope_mode = mode

        session.execute(
            delete(PrincipalCameraScopeEntry).where(
                PrincipalCameraScopeEntry.scope_id == scope.id
            )
        )

        if mode == "selected":
            session.add_all(
                [
                    PrincipalCameraScopeEntry(
                        scope_id=scope.id,
                        camera_id=camera_id,
                    )
                    for camera_id in sorted(unique_camera_ids, key=str)
                ]
                + [
                    PrincipalCameraScopeEntry(
                        scope_id=scope.id,
                        camera_group_id=group_id,
                    )
                    for group_id in sorted(unique_group_ids, key=str)
                ]
            )

        session.flush()
        value = cls.get_scope(
            session,
            principal_type=principal_type,
            principal_id=principal_id,
        )
        assert value is not None
        return value

    @staticmethod
    def _expand_group_camera_ids(
        session: Session,
        selected_group_ids: set[uuid.UUID],
    ) -> set[uuid.UUID]:
        if not selected_group_ids:
            return set()

        groups = list(session.scalars(select(CameraGroup)))
        children: dict[uuid.UUID, set[uuid.UUID]] = {}
        for group in groups:
            if group.parent_id is not None:
                children.setdefault(group.parent_id, set()).add(group.id)

        expanded_groups: set[uuid.UUID] = set()
        pending = list(selected_group_ids)
        while pending:
            group_id = pending.pop()
            if group_id in expanded_groups:
                continue
            expanded_groups.add(group_id)
            pending.extend(children.get(group_id, ()))

        rows = session.execute(
            select(
                CameraGroupMember.camera_group_id,
                CameraGroupMember.camera_id,
            ).where(CameraGroupMember.camera_group_id.in_(expanded_groups))
        ).all()
        return {row.camera_id for row in rows}

    @classmethod
    def _camera_ids_for_scope(
        cls,
        session: Session,
        value: CameraScopeValue,
    ) -> EffectiveCameraScope:
        if value.mode == "all":
            return EffectiveCameraScope(
                all_cameras=True,
                camera_ids=frozenset(),
            )
        if value.mode == "none":
            return EffectiveCameraScope(
                all_cameras=False,
                camera_ids=frozenset(),
            )

        camera_ids = set(value.camera_ids)
        camera_ids.update(
            cls._expand_group_camera_ids(
                session,
                set(value.camera_group_ids),
            )
        )
        return EffectiveCameraScope(
            all_cameras=False,
            camera_ids=frozenset(camera_ids),
        )

    @classmethod
    def effective_scope(
        cls,
        session: Session,
        *,
        user_id: uuid.UUID,
        role_ids: list[uuid.UUID],
    ) -> EffectiveCameraScope:
        user_scope = cls.get_scope(
            session,
            principal_type="user",
            principal_id=user_id,
        )
        if user_scope is not None:
            return cls._camera_ids_for_scope(session, user_scope)

        combined: set[uuid.UUID] = set()
        for role_id in role_ids:
            role_scope = cls.get_scope(
                session,
                principal_type="role",
                principal_id=role_id,
            )
            if role_scope is None:
                continue

            effective = cls._camera_ids_for_scope(session, role_scope)
            if effective.all_cameras:
                return effective
            combined.update(effective.camera_ids)

        return EffectiveCameraScope(
            all_cameras=False,
            camera_ids=frozenset(combined),
        )
