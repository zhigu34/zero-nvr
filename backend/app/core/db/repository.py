"""Single-record lookup helpers shared by services and routers.

Twenty-five call sites repeated the same "load by primary key, otherwise raise a
domain error" block. Nineteen were 404s; the rest used 400/409/422 for a missing
referenced row. Because each copy spelled out its own status code, error code,
and message, the 404 contract had already become inconsistent in ways that are
easy to miss when reading one module at a time — for example
``GET /backups/{id}`` and the backup execution path reported the same missing row
with the same code but were maintained separately.

``fetch_or_raise`` keeps each caller's error identity (status, code, message)
while making the lookup itself shared. ``fetch_or_404`` is the common case.
"""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.core.errors import ApiError

__all__ = ["fetch_or_404", "fetch_or_raise"]

T = TypeVar("T")


def fetch_or_raise(
    session: Session,
    model: type[T],
    identifier: uuid.UUID | Any,
    *,
    status_code: int,
    code: str,
    message: str,
) -> T:
    """Load ``identifier`` from ``model`` or raise :class:`ApiError`."""
    instance = session.get(model, identifier)
    if instance is None:
        raise ApiError(
            status_code=status_code,
            code=code,
            message=message,
        )
    return instance


def fetch_or_404(
    session: Session,
    model: type[T],
    identifier: uuid.UUID | Any,
    *,
    code: str,
    message: str,
) -> T:
    """Load ``identifier`` from ``model`` or raise a 404 :class:`ApiError`."""
    return fetch_or_raise(
        session,
        model,
        identifier,
        status_code=404,
        code=code,
        message=message,
    )
