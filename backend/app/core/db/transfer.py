from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Connection
from sqlalchemy.sql.schema import Table

from app.modules.alerts import models as alert_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.backups import models as backup_models  # noqa: F401
from app.modules.cameras import models as camera_models  # noqa: F401
from app.modules.events import models as event_models  # noqa: F401
from app.modules.exports import models as export_models  # noqa: F401
from app.modules.notifications import models as notification_models  # noqa: F401
from app.modules.recordings import models as recording_models  # noqa: F401
from app.modules.storage import models as storage_models  # noqa: F401
from app.modules.system import models as system_models  # noqa: F401

from .base import Base
from .database import Database
from .schema import assert_database_schema_current


class DatabaseTransferError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DatabaseTransferResult:
    source_backend: str
    target_backend: str
    table_counts: dict[str, int]

    @property
    def total_rows(self) -> int:
        return sum(self.table_counts.values())


class DatabaseTransferService:
    def __init__(
        self,
        *,
        batch_size: int = 500,
    ) -> None:
        if batch_size < 1 or batch_size > 10_000:
            raise ValueError(
                "database transfer batch_size must be between 1 and 10000"
            )
        self.batch_size = batch_size

    @staticmethod
    def _backend(database: Database) -> str:
        name = database.url.get_backend_name()
        return (
            "postgresql"
            if name in {"postgres", "postgresql"}
            else name
        )

    @staticmethod
    def _count(
        connection: Connection,
        table: Table,
    ) -> int:
        return int(
            connection.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
        )

    @staticmethod
    def _self_reference(
        table: Table,
    ) -> tuple[str, str] | None:
        pairs: list[tuple[str, str]] = []
        for constraint in table.foreign_key_constraints:
            for element in constraint.elements:
                if (
                    element.column.table is table
                    and element.parent.table is table
                ):
                    pairs.append(
                        (
                            element.parent.name,
                            element.column.name,
                        )
                    )
        if not pairs:
            return None
        if len(pairs) != 1:
            raise DatabaseTransferError(
                "database_transfer_self_reference_unsupported",
                (
                    "Database transfer encountered a table with an "
                    "unsupported composite or multiple self-reference."
                ),
            )
        return pairs[0]

    @classmethod
    def _ordered_self_referencing_rows(
        cls,
        table: Table,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        reference = cls._self_reference(table)
        if reference is None or not rows:
            return rows

        local_name, remote_name = reference
        known = {
            row.get(remote_name)
            for row in rows
            if row.get(local_name) is None
        }
        remaining = list(rows)
        ordered: list[dict[str, Any]] = []

        while remaining:
            progressed = False
            next_remaining: list[dict[str, Any]] = []
            for row in remaining:
                parent = row.get(local_name)
                if parent is None or parent in known:
                    ordered.append(row)
                    known.add(row.get(remote_name))
                    progressed = True
                else:
                    next_remaining.append(row)

            if not progressed:
                raise DatabaseTransferError(
                    "database_transfer_self_reference_cycle",
                    (
                        "Database transfer found a cyclic or invalid "
                        f"self-reference in table {table.name}."
                    ),
                )
            remaining = next_remaining

        return ordered

    def _assert_target_empty(
        self,
        target: Database,
    ) -> None:
        with target.engine.connect() as connection:
            populated = {
                table.name: self._count(
                    connection,
                    table,
                )
                for table in Base.metadata.sorted_tables
                if self._count(
                    connection,
                    table,
                )
                > 0
            }

        if populated:
            raise DatabaseTransferError(
                "database_transfer_target_not_empty",
                (
                    "Target database contains zero-nvr data and cannot "
                    "be used as a migration destination."
                ),
            )

    def transfer(
        self,
        *,
        source: Database,
        target: Database,
    ) -> DatabaseTransferResult:
        source_backend = self._backend(source)
        target_backend = self._backend(target)
        if source_backend == target_backend:
            # Same-backend transfer is supported by the implementation and
            # used by unit tests, but callers should make this choice explicit.
            pass

        assert_database_schema_current(source)
        assert_database_schema_current(target)
        self._assert_target_empty(target)

        counts: dict[str, int] = {}
        with source.engine.connect() as source_connection:
            with target.engine.begin() as target_connection:
                for table in Base.metadata.sorted_tables:
                    source_count = self._count(
                        source_connection,
                        table,
                    )
                    counts[table.name] = source_count
                    if source_count == 0:
                        continue

                    self_reference = self._self_reference(
                        table
                    )
                    if self_reference is not None:
                        rows = [
                            dict(item)
                            for item in source_connection.execute(
                                select(table)
                            ).mappings()
                        ]
                        ordered = (
                            self._ordered_self_referencing_rows(
                                table,
                                rows,
                            )
                        )
                        for start in range(
                            0,
                            len(ordered),
                            self.batch_size,
                        ):
                            target_connection.execute(
                                table.insert(),
                                ordered[
                                    start : start
                                    + self.batch_size
                                ],
                            )
                    else:
                        result = source_connection.execution_options(
                            stream_results=True
                        ).execute(
                            select(table)
                        ).mappings()
                        while True:
                            batch = result.fetchmany(
                                self.batch_size
                            )
                            if not batch:
                                break
                            target_connection.execute(
                                table.insert(),
                                [
                                    dict(item)
                                    for item in batch
                                ],
                            )

                    target_count = self._count(
                        target_connection,
                        table,
                    )
                    if target_count != source_count:
                        raise DatabaseTransferError(
                            "database_transfer_count_mismatch",
                            (
                                "Database transfer row-count verification "
                                f"failed for table {table.name}."
                            ),
                        )

        return DatabaseTransferResult(
            source_backend=source_backend,
            target_backend=target_backend,
            table_counts=counts,
        )
