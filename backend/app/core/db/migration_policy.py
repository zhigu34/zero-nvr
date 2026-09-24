from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


POSTGRESQL_MIGRATION_LOCK_TIMEOUT_MS = 5_000
POSTGRESQL_MIGRATION_STATEMENT_TIMEOUT_MS = 300_000


class MigrationClass(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class SQLiteMigrationStrategy(StrEnum):
    DIRECT = "direct"
    BATCH = "batch"
    REBUILD = "rebuild"


class PostgreSQLMigrationStrategy(StrEnum):
    TRANSACTIONAL = "transactional"
    TRANSACTIONAL_RESTARTABLE = (
        "transactional_restartable"
    )
    BATCHED_RESTARTABLE = "batched_restartable"


@dataclass(frozen=True, slots=True)
class MigrationPolicy:
    revision: str
    migration_class: MigrationClass
    sqlite_strategy: SQLiteMigrationStrategy
    rationale: str
    postgresql_strategy: PostgreSQLMigrationStrategy = (
        PostgreSQLMigrationStrategy.TRANSACTIONAL
    )

    def __post_init__(self) -> None:
        if (
            self.migration_class
            in {MigrationClass.B, MigrationClass.C}
            and self.postgresql_strategy
            is PostgreSQLMigrationStrategy.TRANSACTIONAL
        ):
            raise ValueError(
                "Class B/C migration must explicitly "
                "declare restartable PostgreSQL behavior"
            )

    @property
    def requires_verified_backup(self) -> bool:
        return self.migration_class is MigrationClass.C

    @property
    def requires_maintenance(self) -> bool:
        return self.migration_class is MigrationClass.C


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    current_revisions: frozenset[str]
    pending: tuple[MigrationPolicy, ...]

    @property
    def highest_class(self) -> MigrationClass | None:
        if not self.pending:
            return None
        order = {
            MigrationClass.A: 1,
            MigrationClass.B: 2,
            MigrationClass.C: 3,
        }
        return max(
            (
                item.migration_class
                for item in self.pending
            ),
            key=order.__getitem__,
        )

    @property
    def requires_verified_backup(self) -> bool:
        return bool(self.current_revisions) and any(
            item.requires_verified_backup
            for item in self.pending
        )

    @property
    def requires_maintenance(self) -> bool:
        return bool(self.current_revisions) and any(
            item.requires_maintenance
            for item in self.pending
        )

    @property
    def requires_sqlite_checkpoint(self) -> bool:
        return bool(self.current_revisions) and any(
            item.sqlite_strategy
            is not SQLiteMigrationStrategy.DIRECT
            for item in self.pending
        )


MIGRATION_POLICIES: tuple[MigrationPolicy, ...] = (
    MigrationPolicy(
        "0001_auth_rbac",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "foundation tables",
    ),
    MigrationPolicy(
        "0002_system_audit",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "add system settings and audit tables",
    ),
    MigrationPolicy(
        "0003_camera_inventory",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "add camera/device inventory tables",
    ),
    MigrationPolicy(
        "0004_recording_catalog",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "add recording/storage catalog tables",
    ),
    MigrationPolicy(
        "0005_events",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "add event table and indexes",
    ),
    MigrationPolicy(
        "0006_alerts_notifications",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "add alert and notification tables",
    ),
    MigrationPolicy(
        "0007_exports",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "add export tables",
    ),
    MigrationPolicy(
        "0008_backups",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "add backup policy and set tables",
    ),
    MigrationPolicy(
        "0009_camera_retirement",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "add nullable camera retirement state",
    ),
    MigrationPolicy(
        "0010_notification_delivery",
        MigrationClass.B,
        SQLiteMigrationStrategy.REBUILD,
        "transform notification delivery rows into frozen V1 schema",
        PostgreSQLMigrationStrategy.TRANSACTIONAL_RESTARTABLE,
    ),
    MigrationPolicy(
        "0011_live_view_layouts",
        MigrationClass.A,
        SQLiteMigrationStrategy.DIRECT,
        "add live-view layout table",
    ),
    MigrationPolicy(
        "0012_notification_secret",
        MigrationClass.A,
        SQLiteMigrationStrategy.BATCH,
        "relax notification secret nullability",
    ),
    MigrationPolicy(
        "0013_user_email_verified",
        MigrationClass.A,
        SQLiteMigrationStrategy.BATCH,
        "add nullable email verification timestamp",
    ),
    MigrationPolicy(
        "0014_notification_smtp",
        MigrationClass.A,
        SQLiteMigrationStrategy.BATCH,
        "extend notification target kind constraint",
    ),
    MigrationPolicy(
        "0015_camera_time_sync_mode",
        MigrationClass.B,
        SQLiteMigrationStrategy.BATCH,
        "add and backfill camera time synchronization mode",
        PostgreSQLMigrationStrategy.TRANSACTIONAL_RESTARTABLE,
    ),
    MigrationPolicy(
        "0016_camera_config_revision",
        MigrationClass.A,
        SQLiteMigrationStrategy.BATCH,
        "add camera configuration revision fencing",
    ),
    MigrationPolicy(
        "0017_camera_maintenance",
        MigrationClass.A,
        SQLiteMigrationStrategy.BATCH,
        "add camera maintenance state",
    ),
)

_POLICY_BY_REVISION = {
    item.revision: item
    for item in MIGRATION_POLICIES
}


def migration_policy(
    revision: str,
) -> MigrationPolicy:
    try:
        return _POLICY_BY_REVISION[revision]
    except KeyError as exc:
        raise RuntimeError(
            "migration revision has no A/B/C policy: "
            f"{revision}"
        ) from exc


def build_migration_plan(
    current_revisions: frozenset[str],
) -> MigrationPlan:
    if len(current_revisions) > 1:
        raise RuntimeError(
            "V1 migration policy requires a linear "
            "single-head database history"
        )

    if not current_revisions:
        return MigrationPlan(
            current_revisions=current_revisions,
            pending=MIGRATION_POLICIES,
        )

    current = next(iter(current_revisions))
    current_policy = migration_policy(current)
    index = MIGRATION_POLICIES.index(
        current_policy
    )
    return MigrationPlan(
        current_revisions=current_revisions,
        pending=MIGRATION_POLICIES[
            index + 1:
        ],
    )



def migration_context_options(
    dialect_name: str,
) -> dict[str, bool]:
    return {
        "render_as_batch": dialect_name == "sqlite",
        "transaction_per_migration": (
            dialect_name == "postgresql"
        ),
    }


def configure_postgresql_migration_session(
    connection: Any,
) -> None:
    if connection.dialect.name != "postgresql":
        return

    connection.exec_driver_sql(
        "SET lock_timeout = "
        f"'{POSTGRESQL_MIGRATION_LOCK_TIMEOUT_MS}ms'"
    )
    connection.exec_driver_sql(
        "SET statement_timeout = "
        f"'{POSTGRESQL_MIGRATION_STATEMENT_TIMEOUT_MS}ms'"
    )
    connection.commit()
