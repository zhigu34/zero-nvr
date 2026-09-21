from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db_session
from app.core.errors import ApiError
from app.modules.auth.dependencies import (
    get_effective_camera_scope,
    require_permission,
)
from app.modules.auth.service import AuthContext

from .models import Camera, LiveViewLayout


router = APIRouter()


class LiveViewLayoutState(BaseModel):
    slots: Literal[1, 4, 9, 16] = 4
    camera_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=16,
    )
    camera_panel_open: bool = True

    @field_validator("camera_ids")
    @classmethod
    def unique_camera_ids(
        cls,
        value: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError(
                "camera_ids must not contain duplicates"
            )
        return value


class LiveViewLayoutCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    is_default: bool = False
    layout: LiveViewLayoutState

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class LiveViewLayoutUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    is_default: bool | None = None
    layout: LiveViewLayoutState | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class LiveViewLayoutView(BaseModel):
    id: uuid.UUID
    name: str
    is_default: bool
    layout: LiveViewLayoutState
    created_at: datetime
    updated_at: datetime


def _owned_layout(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    layout_id: uuid.UUID,
) -> LiveViewLayout:
    layout = session.scalar(
        select(LiveViewLayout).where(
            LiveViewLayout.id == layout_id,
            LiveViewLayout.owner_user_id
            == owner_user_id,
        )
    )
    if layout is None:
        raise ApiError(
            status_code=404,
            code="live_view_layout_not_found",
            message="Live view layout was not found.",
        )
    return layout


def _ensure_unique_name(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    query = select(LiveViewLayout.id).where(
        LiveViewLayout.owner_user_id
        == owner_user_id,
        LiveViewLayout.name == name,
    )
    if exclude_id is not None:
        query = query.where(
            LiveViewLayout.id != exclude_id
        )
    if session.scalar(query) is not None:
        raise ApiError(
            status_code=409,
            code="live_view_layout_name_conflict",
            message=(
                "A live view layout with that name "
                "already exists."
            ),
        )


def _clear_defaults(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    exclude_id: uuid.UUID | None = None,
) -> None:
    layouts = session.scalars(
        select(LiveViewLayout).where(
            LiveViewLayout.owner_user_id
            == owner_user_id,
            LiveViewLayout.is_default.is_(True),
        )
    ).all()
    for layout in layouts:
        if (
            exclude_id is not None
            and layout.id == exclude_id
        ):
            continue
        layout.is_default = False
    session.flush()


def _require_state_access(
    session: Session,
    *,
    state: LiveViewLayoutState,
    context: AuthContext,
) -> None:
    if not state.camera_ids:
        return

    scope = get_effective_camera_scope(
        context,
        session,
    )
    requested = set(state.camera_ids)
    if (
        not scope.all_cameras
        and not requested.issubset(scope.camera_ids)
    ):
        raise ApiError(
            status_code=400,
            code="live_view_layout_camera_unavailable",
            message=(
                "One or more cameras are unavailable "
                "for this live view layout."
            ),
        )

    available = set(
        session.scalars(
            select(Camera.id).where(
                Camera.id.in_(requested),
                Camera.retired_at.is_(None),
                Camera.enabled.is_(True),
            )
        ).all()
    )
    if available != requested:
        raise ApiError(
            status_code=400,
            code="live_view_layout_camera_unavailable",
            message=(
                "One or more cameras are unavailable "
                "for this live view layout."
            ),
        )


def _visible_state(
    session: Session,
    *,
    layout: LiveViewLayout,
    context: AuthContext,
) -> LiveViewLayoutState:
    try:
        state = LiveViewLayoutState.model_validate(
            layout.layout_json or {}
        )
    except ValidationError:
        state = LiveViewLayoutState()

    if not state.camera_ids:
        return state

    scope = get_effective_camera_scope(
        context,
        session,
    )
    available = set(
        session.scalars(
            select(Camera.id).where(
                Camera.id.in_(state.camera_ids),
                Camera.retired_at.is_(None),
                Camera.enabled.is_(True),
            )
        ).all()
    )
    if not scope.all_cameras:
        available.intersection_update(
            scope.camera_ids
        )

    return state.model_copy(
        update={
            "camera_ids": [
                camera_id
                for camera_id in state.camera_ids
                if camera_id in available
            ]
        }
    )


def _view(
    session: Session,
    *,
    layout: LiveViewLayout,
    context: AuthContext,
) -> LiveViewLayoutView:
    return LiveViewLayoutView(
        id=layout.id,
        name=layout.name,
        is_default=layout.is_default,
        layout=_visible_state(
            session,
            layout=layout,
            context=context,
        ),
        created_at=layout.created_at,
        updated_at=layout.updated_at,
    )


@router.get(
    "/live-layouts",
    response_model=list[LiveViewLayoutView],
)
def list_live_view_layouts(
    context: AuthContext = Depends(
        require_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> list[LiveViewLayoutView]:
    layouts = session.scalars(
        select(LiveViewLayout)
        .where(
            LiveViewLayout.owner_user_id
            == context.user.id
        )
        .order_by(
            LiveViewLayout.is_default.desc(),
            LiveViewLayout.updated_at.desc(),
            LiveViewLayout.name.asc(),
        )
    ).all()
    return [
        _view(
            session,
            layout=layout,
            context=context,
        )
        for layout in layouts
    ]


@router.post(
    "/live-layouts",
    response_model=LiveViewLayoutView,
    status_code=201,
)
def create_live_view_layout(
    body: LiveViewLayoutCreate,
    context: AuthContext = Depends(
        require_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> LiveViewLayoutView:
    _ensure_unique_name(
        session,
        owner_user_id=context.user.id,
        name=body.name,
    )
    _require_state_access(
        session,
        state=body.layout,
        context=context,
    )
    count = session.scalar(
        select(func.count())
        .select_from(LiveViewLayout)
        .where(
            LiveViewLayout.owner_user_id
            == context.user.id
        )
    )
    make_default = body.is_default or not count
    if make_default:
        _clear_defaults(
            session,
            owner_user_id=context.user.id,
        )

    layout = LiveViewLayout(
        owner_user_id=context.user.id,
        name=body.name,
        is_default=make_default,
        layout_json=body.layout.model_dump(
            mode="json"
        ),
    )
    session.add(layout)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            status_code=409,
            code="live_view_layout_conflict",
            message=(
                "The live view layout could not "
                "be saved because it conflicts "
                "with another layout."
            ),
        ) from exc
    session.refresh(layout)
    return _view(
        session,
        layout=layout,
        context=context,
    )


@router.patch(
    "/live-layouts/{layout_id}",
    response_model=LiveViewLayoutView,
)
def update_live_view_layout(
    layout_id: uuid.UUID,
    body: LiveViewLayoutUpdate,
    context: AuthContext = Depends(
        require_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> LiveViewLayoutView:
    layout = _owned_layout(
        session,
        owner_user_id=context.user.id,
        layout_id=layout_id,
    )

    if body.name is not None:
        _ensure_unique_name(
            session,
            owner_user_id=context.user.id,
            name=body.name,
            exclude_id=layout.id,
        )
        layout.name = body.name

    if body.layout is not None:
        _require_state_access(
            session,
            state=body.layout,
            context=context,
        )
        layout.layout_json = (
            body.layout.model_dump(mode="json")
        )

    if body.is_default is True:
        _clear_defaults(
            session,
            owner_user_id=context.user.id,
            exclude_id=layout.id,
        )
        layout.is_default = True
    elif body.is_default is False:
        layout.is_default = False

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            status_code=409,
            code="live_view_layout_conflict",
            message=(
                "The live view layout could not "
                "be updated because it conflicts "
                "with another layout."
            ),
        ) from exc
    session.refresh(layout)
    return _view(
        session,
        layout=layout,
        context=context,
    )


@router.delete(
    "/live-layouts/{layout_id}",
    status_code=204,
)
def delete_live_view_layout(
    layout_id: uuid.UUID,
    context: AuthContext = Depends(
        require_permission("camera.view")
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    layout = _owned_layout(
        session,
        owner_user_id=context.user.id,
        layout_id=layout_id,
    )
    session.delete(layout)
    session.commit()
    return Response(status_code=204)
