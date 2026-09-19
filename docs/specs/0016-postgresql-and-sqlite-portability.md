# Spec 0016 — SQLite and PostgreSQL Production Database Modes

Status: **accepted**

## Goal

Define the first-production-release database strategy for zero-nvr.

Core rule:

> SQLite is the default lightweight production database. PostgreSQL is an optional enhanced production database. Both support the same product features; they differ in scale, concurrency behavior, backup engine, and operational profile.

## Production modes

```text
Database Mode

SQLite
  default
  lightweight single-host
  no separate DB service
  WAL mode
  SQLite Online Backup + Litestream

PostgreSQL
  optional enhanced mode
  higher write concurrency
  larger installations
  external/managed DB support
  pgBackRest + WAL/PITR
```

The product must not artificially disable camera, recording, alert, storage, authentication, integration, playback, or backup features merely because SQLite is selected.

## Default deployment

The default zero-nvr deployment uses SQLite.

```text
zero-nvr
  web
  api
  worker
  zlmediakit
  /data/zero-nvr/zero-nvr.db
```

No PostgreSQL container is required in the default lightweight stack.

The PostgreSQL deployment profile adds an internal PostgreSQL service or points to an external PostgreSQL instance.

## SQLite production requirements

SQLite production mode uses:

```text
journal_mode = WAL
foreign_keys = ON
busy timeout / bounded retry
short write transactions
controlled checkpointing
batched metadata writes where useful
```

The SQLite database file must live on a supported local filesystem.

Do not place the live SQLite database/WAL on NFS, SMB, WebDAV, OpenList, or object storage.

Recording media may still use mounted/local/remote storage independently.

## Write-concurrency strategy

SQLite allows many readers but serializes writers.

zero-nvr therefore designs the persistence layer so SQLite mode:

- keeps write transactions short;
- avoids network/media operations inside transactions;
- batches high-frequency metadata where safe;
- retries bounded SQLITE_BUSY conditions;
- monitors write latency, busy count, WAL size, checkpoint duration, and write backlog;
- does not require long-lived database locks for worker orchestration.

When the observed workload outgrows SQLite, the product recommends PostgreSQL rather than silently degrading correctness.

## PostgreSQL mode

PostgreSQL is recommended when the installation has sustained high metadata write concurrency, many workers, heavy AI/event streams, large multi-user workloads, or future deployment requirements that benefit from client/server database semantics.

PostgreSQL-specific implementation may use richer locking/indexing features internally, but user-visible domain behavior remains the same.

## Database abstraction

Do not scatter dialect branches throughout business code.

```text
Domain / Application Services
          ↓
Repository + Unit of Work
          ↓
DatabaseCapabilities
      ┌──────────────┐
      │              │
SQLiteBackend   PostgreSQLBackend
```

DatabaseCapabilities owns backend-specific infrastructure behavior such as:

- task claiming/coordination;
- locking strategy;
- JSON/index optimizations;
- backup adapter;
- health metrics;
- migration/export mechanics.

Business invariants remain database-independent.

## Schema policy

Use a common logical schema wherever practical:

```text
UUID/string IDs
UTC timestamps
JSON metadata
foreign keys
unique constraints
normal relational indexes
```

Do not weaken correctness simply to force identical physical SQL.

Backend-specific indexes/locking/DDL are allowed behind migrations/capability code.

## Testing policy

Both production modes are supported, therefore both receive production integration tests.

Required CI categories:

```text
shared domain tests
SQLite production-mode integration tests
PostgreSQL production-mode integration tests
cross-backend migration tests
backup/restore tests for each backend
```

SQLite-only tests never substitute for PostgreSQL tests and vice versa.

## Database selection UI

Initial setup includes:

```text
Database

● SQLite
  Recommended for most single-host installations
  Lowest resource usage

○ PostgreSQL
  Recommended for high write concurrency / larger installations
```

Advanced PostgreSQL settings may select:

- bundled PostgreSQL deployment;
- external PostgreSQL connection.

Changing database mode after initialization is handled through the migration workflow, not by editing a connection string behind the product.

## SQLite to PostgreSQL migration

First production release supports guided migration.

```text
preflight
  ↓
create verified safety backup
  ↓
maintenance mode
  ↓
quiesce DB-mutating workers
  ↓
consistent SQLite snapshot
  ↓
create/migrate PostgreSQL schema
  ↓
copy canonical data
  ↓
validate row counts / relations / critical invariants
  ↓
switch active backend
  ↓
restart/reconcile
```

Failure before cutover leaves SQLite authoritative and usable.

## PostgreSQL to SQLite migration

Reverse migration is supported when the current data/workload fits SQLite constraints and no unsupported backend-specific operational dependency blocks the move.

Preflight checks:

- database size;
- write rate/history;
- worker topology;
- schema compatibility;
- pending jobs;
- JSON/data conversion;
- available local disk;
- backup health.

The UI may warn strongly when metrics indicate SQLite is a poor fit, but it does not arbitrarily remove business features.

## Migration identity

Database migration must preserve canonical IDs and timestamps.

Do not create new Camera/Recording/Event identities merely because the database backend changes.

## Automatic recommendation

SQLite health exposes at least:

```text
write_latency
busy_retry_count
write_queue_depth
wal_size
checkpoint_duration
database_size
transaction_latency
```

If sustained thresholds are exceeded, the UI can recommend:

```text
Database write pressure is high.
Consider migrating to PostgreSQL.
```

Thresholds are tuning/health settings, not hard camera-count limits.

## SQLite portable index

SQLite production support does not remove the separate portable-index concept.

A metadata-only or selected-media export may still produce a versioned standalone SQLite package for:

- detached-media inspection;
- support diagnostics;
- migration/import;
- offline analysis.

Portable exports remain separate from the live SQLite production file and follow export authorization/sanitization rules.

## Backup relationship

Database backup is selected by active backend:

```text
SQLite
  ├─ SQLite Online Backup API -> consistent snapshots
  └─ Litestream -> continuous remote replication / point-in-time restore

PostgreSQL
  └─ pgBackRest -> full/diff/incr + WAL/PITR
```

Spec 0015 defines the unified backup product model.

## Invariants

1. SQLite is the default supported production database.
2. PostgreSQL is an optional fully supported enhanced production database.
3. User-visible product features are not intentionally reduced in SQLite mode.
4. SQLite production uses WAL mode, short transactions, bounded retry, and a local filesystem.
5. PostgreSQL remains available for workloads needing greater concurrent-write capacity.
6. Backend-specific behavior stays behind database/persistence capabilities rather than leaking into domain logic.
7. Both database modes receive production integration, migration, and backup/restore testing.
8. Guided SQLite-to-PostgreSQL migration is part of the first production release.
9. Reverse migration performs compatibility/load preflight rather than blindly copying data.
10. Canonical business identities survive database migration.
11. Backup implementation is backend-specific while the BackupPolicy/Restore UX remains unified.
12. Non-obvious cross-database transaction, migration, and retry behavior requires comments per Development Guidelines.

## Software-upgrade relationship

SQLite ↔ PostgreSQL migration is intentionally separate from normal application upgrade. A release upgrade keeps the selected database engine unless the administrator starts a dedicated DatabaseMigrationPlan.

Both engines must pass upgrade/schema migration tests and use their database-specific verified safety-backup path before incompatible changes.

See [Spec 0017 — Upgrade, Schema Migration, Database Migration, and Rollback](0017-upgrade-migration-and-rollback.md).
