from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.modules.alerts.models import Alert
from app.modules.audit.models import AuditEvent
from app.modules.events.models import Event
from app.modules.recordings.models import RecordingSegment

from .database import Database
from .schema import database_schema_status
from .types import utc_now


@dataclass(frozen=True, slots=True)
class SQLiteMigrationPreflight:
    source_backend: str
    schema_current: bool
    schema_current_revisions: tuple[str, ...]
    schema_expected_revisions: tuple[str, ...]
    source_database_bytes: int | None
    target_free_bytes: int
    required_target_free_bytes: int | None
    recent_window_seconds: int
    recent_writes: dict[str, int]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def recent_write_rows(self) -> int:
        return sum(self.recent_writes.values())

    @property
    def allowed(self) -> bool:
        return not self.blockers


class SQLiteMigrationPreflightService:
    """Measured PostgreSQL -> SQLite migration checks.

    This deliberately does not infer SQLite suitability from camera count.
    Workload suitability still requires operator confirmation after reviewing
    measured activity and prior representative SQLite benchmark/soak evidence.
    """

    recent_window = timedelta(hours=1)
    target_headroom_bytes = 512 * 1024 * 1024

    @staticmethod
    def _backend(database: Database) -> str:
        backend = database.url.get_backend_name()
        return (
            "postgresql"
            if backend in {"postgres", "postgresql"}
            else backend
        )

    @classmethod
    def _source_database_bytes(
        cls,
        database: Database,
    ) -> int:
        with database.engine.connect() as connection:
            return int(
                connection.execute(
                    select(
                        func.pg_database_size(
                            func.current_database()
                        )
                    )
                ).scalar_one()
            )

    @classmethod
    def _recent_writes(
        cls,
        database: Database,
    ) -> dict[str, int]:
        cutoff = utc_now() - cls.recent_window
        sources = (
            (
                "recording_segments",
                RecordingSegment,
                RecordingSegment.created_at,
            ),
            (
                "events",
                Event,
                Event.created_at,
            ),
            (
                "alerts",
                Alert,
                Alert.created_at,
            ),
            (
                "audit_events",
                AuditEvent,
                AuditEvent.created_at,
            ),
        )
        counts: dict[str, int] = {}
        with database.session() as session:
            for name, model, created_at in sources:
                counts[name] = int(
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(created_at >= cutoff)
                    )
                    or 0
                )
        return counts

    @classmethod
    def collect(
        cls,
        database: Database,
        *,
        target_root: Path,
    ) -> SQLiteMigrationPreflight:
        backend = cls._backend(database)
        schema = database_schema_status(database)
        target_root = target_root.resolve()
        disk = shutil.disk_usage(target_root)

        blockers: list[str] = []
        warnings: list[str] = []
        source_bytes: int | None = None
        required_bytes: int | None = None
        recent_writes: dict[str, int] = {}

        if backend != "postgresql":
            blockers.append(
                "sqlite_preflight_source_not_postgresql"
            )
        if not schema.compatible:
            blockers.append(
                "sqlite_preflight_source_schema_not_current"
            )

        if backend == "postgresql" and schema.compatible:
            source_bytes = cls._source_database_bytes(
                database
            )
            required_bytes = max(
                source_bytes * 2,
                source_bytes + cls.target_headroom_bytes,
            )
            if disk.free < required_bytes:
                blockers.append(
                    "sqlite_preflight_target_disk_space_insufficient"
                )

            recent_writes = cls._recent_writes(
                database
            )
            if sum(recent_writes.values()) > 0:
                warnings.append(
                    "sqlite_preflight_recent_write_activity_observed"
                )

        warnings.append(
            "sqlite_preflight_workload_confirmation_required"
        )

        return SQLiteMigrationPreflight(
            source_backend=backend,
            schema_current=schema.compatible,
            schema_current_revisions=tuple(
                sorted(schema.current)
            ),
            schema_expected_revisions=tuple(
                sorted(schema.expected)
            ),
            source_database_bytes=source_bytes,
            target_free_bytes=disk.free,
            required_target_free_bytes=required_bytes,
            recent_window_seconds=int(
                cls.recent_window.total_seconds()
            ),
            recent_writes=recent_writes,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )
