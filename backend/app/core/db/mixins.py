from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from .types import UTCDateTime, UUIDType, utc_now


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
