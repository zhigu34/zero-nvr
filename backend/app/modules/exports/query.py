from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError

from .models import ExportJob


@dataclass(frozen=True, slots=True)
class ExportPageResult:
    items: list[ExportJob]
    next_cursor: str | None


def _encode_cursor(item: ExportJob) -> str:
    payload = json.dumps(
        {
            "created_at": item.created_at.astimezone(UTC).isoformat(),
            "id": str(item.id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(
        payload
    ).decode("ascii").rstrip("=")


def _decode_cursor(
    value: str,
) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(
                value + padding
            ).decode("utf-8")
        )
        created_at = datetime.fromisoformat(
            payload["created_at"]
        )
        if (
            created_at.tzinfo is None
            or created_at.utcoffset() is None
        ):
            raise ValueError
        return (
            created_at.astimezone(UTC),
            uuid.UUID(payload["id"]),
        )
    except (
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raise ApiError(
            status_code=400,
            code="export_cursor_invalid",
            message="Export cursor is invalid.",
        ) from exc


class ExportQueryService:
    @staticmethod
    def list(
        session: Session,
        *,
        allowed_camera_ids: frozenset[uuid.UUID] | None,
        state: str | None,
        cursor: str | None,
        limit: int,
    ) -> ExportPageResult:
        if limit < 1 or limit > 200:
            raise ApiError(
                status_code=400,
                code="export_limit_invalid",
                message="Export limit must be between 1 and 200.",
            )

        statement = select(ExportJob)
        if allowed_camera_ids is not None:
            if not allowed_camera_ids:
                return ExportPageResult(
                    items=[],
                    next_cursor=None,
                )
            statement = statement.where(
                ExportJob.camera_id.in_(allowed_camera_ids)
            )
        if state is not None:
            allowed_states = {
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "EXPIRED",
            }
            if state not in allowed_states:
                raise ApiError(
                    status_code=400,
                    code="export_state_invalid",
                    message="Export state is invalid.",
                )
            statement = statement.where(
                ExportJob.state == state
            )

        if cursor is not None:
            created_at, export_id = _decode_cursor(
                cursor
            )
            statement = statement.where(
                or_(
                    ExportJob.created_at < created_at,
                    and_(
                        ExportJob.created_at == created_at,
                        ExportJob.id < export_id,
                    ),
                )
            )

        rows = list(
            session.scalars(
                statement.order_by(
                    ExportJob.created_at.desc(),
                    ExportJob.id.desc(),
                ).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        return ExportPageResult(
            items=items,
            next_cursor=(
                _encode_cursor(items[-1])
                if has_more and items
                else None
            ),
        )
