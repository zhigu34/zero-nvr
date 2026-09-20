from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError

from .models import BackupSet


@dataclass(frozen=True, slots=True)
class BackupSetPageResult:
    items: list[BackupSet]
    next_cursor: str | None


def _encode_cursor(item: BackupSet) -> str:
    payload = json.dumps(
        {
            "started_at": item.started_at.astimezone(UTC).isoformat(),
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
        started_at = datetime.fromisoformat(
            payload["started_at"]
        )
        if (
            started_at.tzinfo is None
            or started_at.utcoffset() is None
        ):
            raise ValueError
        return (
            started_at.astimezone(UTC),
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
            code="backup_cursor_invalid",
            message="Backup cursor is invalid.",
        ) from exc


class BackupQueryService:
    @staticmethod
    def list(
        session: Session,
        *,
        policy_id: uuid.UUID | None,
        state: str | None,
        cursor: str | None,
        limit: int,
    ) -> BackupSetPageResult:
        if limit < 1 or limit > 200:
            raise ApiError(
                status_code=400,
                code="backup_limit_invalid",
                message="Backup limit must be between 1 and 200.",
            )

        statement = select(BackupSet)
        if policy_id is not None:
            statement = statement.where(
                BackupSet.backup_policy_id == policy_id
            )
        if state is not None:
            if state not in {
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "FAILED",
            }:
                raise ApiError(
                    status_code=400,
                    code="backup_state_invalid",
                    message="Backup state is invalid.",
                )
            statement = statement.where(
                BackupSet.state == state
            )

        if cursor is not None:
            started_at, backup_id = _decode_cursor(
                cursor
            )
            statement = statement.where(
                or_(
                    BackupSet.started_at < started_at,
                    and_(
                        BackupSet.started_at == started_at,
                        BackupSet.id < backup_id,
                    ),
                )
            )

        rows = list(
            session.scalars(
                statement.order_by(
                    BackupSet.started_at.desc(),
                    BackupSet.id.desc(),
                ).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        return BackupSetPageResult(
            items=items,
            next_cursor=(
                _encode_cursor(items[-1])
                if has_more and items
                else None
            ),
        )
