from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, inspect, select

from app.modules.alerts import models as alert_models
from app.modules.audit import models as audit_models
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.backups import models as backup_models  # noqa: F401
from app.modules.cameras import models as camera_models  # noqa: F401
from app.modules.events import models as event_models
from app.modules.exports import models as export_models  # noqa: F401
from app.modules.notifications import models as notification_models  # noqa: F401
from app.modules.recordings import models as recording_models
from app.modules.storage import models as storage_models  # noqa: F401
from app.modules.system import models as system_models  # noqa: F401

from .base import Base
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
    missing_canonical_tables: tuple[str, ...]
    unexpected_tables: tuple[str, ...]
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
                recording_models.RecordingSegment,
                recording_models.RecordingSegment.created_at,
            ),
            (
                "events",
                event_models.Event,
                event_models.Event.created_at,
            ),
            (
                "alerts",
                alert_models.Alert,
                alert_models.Alert.created_at,
            ),
            (
                "audit_events",
                audit_models.AuditEvent,
                audit_models.AuditEvent.created_at,
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
        missing_tables: tuple[str, ...] = ()
        unexpected_tables: tuple[str, ...] = ()
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

        if backend == "postgresql":
            actual_tables = set(
                inspect(database.engine).get_table_names()
            )
            canonical_tables = set(
                Base.metadata.tables
            )
            missing_tables = tuple(
                sorted(
                    canonical_tables - actual_tables
                )
            )
            unexpected_tables = tuple(
                sorted(
                    actual_tables
                    - canonical_tables
                    - {"alembic_version"}
                )
            )
            if missing_tables:
                blockers.append(
                    "sqlite_preflight_canonical_tables_missing"
                )
            if unexpected_tables:
                blockers.append(
                    "sqlite_preflight_unmanaged_tables_present"
                )

        if (
            backend == "postgresql"
            and schema.compatible
            and not missing_tables
            and not unexpected_tables
        ):
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
            "sqlite_preflight_review_measured_workload"
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
            missing_canonical_tables=missing_tables,
            unexpected_tables=unexpected_tables,
            target_free_bytes=disk.free,
            required_target_free_bytes=required_bytes,
            recent_window_seconds=int(
                cls.recent_window.total_seconds()
            ),
            recent_writes=recent_writes,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )
