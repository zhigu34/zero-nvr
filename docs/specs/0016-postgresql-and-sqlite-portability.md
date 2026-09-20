# Spec 0016 — SQLite and PostgreSQL Production Database Modes

Status: **accepted**

## Goal

Keep SQLite as the default first-class production database while offering PostgreSQL as an optional scale-up path, without maintaining two different products.

Core rule:

> One domain model, one SQLAlchemy/Alembic codebase, SQLite by default, PostgreSQL when the measured workload or deployment requires it.

## Default

Core uses SQLite:

~~~text
zero-nvr API
zero-nvr worker
ZLMediaKit
/data/zero-nvr/zero-nvr.db
~~~

No PostgreSQL container is required for the default deployment.

PostgreSQL may be:

- managed by the zero-nvr Compose profile; or
- an external database.

## SQLite production configuration

SQLite mode uses, as appropriate:

~~~text
journal_mode = WAL
foreign_keys = ON
busy_timeout
short write transactions
controlled checkpoints
sensible synchronous setting
~~~

The live SQLite DB/WAL must be on a supported local filesystem.

Do not place the live database on NFS/SMB/WebDAV/OpenList/object storage.

Recording media storage is independent.

## SQLite write strategy

SQLite serializes writers, so application design must:

- keep write transactions short;
- never hold a transaction while doing camera/network/rclone/FFmpeg work;
- avoid high-frequency telemetry writes;
- batch safe low-value updates when useful;
- handle SQLITE_BUSY with bounded retry;
- keep Huey/job semantics compatible with SQLite;
- drive retention scans from bounded camera/end-time indexes rather than whole-location scans;
- refresh planner statistics after large imports/migrations and periodically through normal SQLite maintenance.

Do not introduce Redis/PostgreSQL merely to compensate for avoidable application write amplification.

## PostgreSQL mode

PostgreSQL is optional for:

- sustained higher metadata/event write concurrency;
- larger installations;
- multi-user workloads;
- deployments already standardized on PostgreSQL.

It does not unlock a different set of product features.

## ORM and migration

Use:

- SQLAlchemy 2.x;
- Alembic.

Keep the logical schema portable:

- normal relational tables/foreign keys;
- timezone-safe timestamps;
- JSON only where bounded metadata is appropriate;
- portable constraints/indexes where practical.

Avoid making PostgreSQL-only arrays/extensions/JSON queries central to normal business behavior.

## Database-specific code

Do not build a large DatabaseCapabilities framework before it is needed.

Prefer:

~~~text
domain/service
-> SQLAlchemy repository/query
-> small dialect-specific helper only where behavior truly differs
~~~

Legitimate differences may include:

- lock/claim syntax;
- migration DDL;
- backup command;
- health diagnostics;
- selected index optimization.

Keep those differences narrow and tested.

## Background jobs

Huey remains the background-job system.

SQLite deployments may use its SQLite-supported mode; PostgreSQL deployments may use its PostgreSQL-supported mode.

Do not make Redis/Celery/RabbitMQ mandatory.

## Backup

V1:

~~~text
SQLite
  -> SQLite Online Backup API
  -> restic

PostgreSQL
  -> pg_dump
  -> restic
~~~

Litestream, pgBackRest, WAL/PITR, and similar advanced recovery systems are optional future integrations, not baseline dependencies.

See [Spec 0015](0015-backup-disaster-recovery-and-pitr.md).

## Selection at install

Default .env/deployment choice:

~~~text
DATABASE=sqlite
~~~

Optional:

~~~text
DATABASE=postgres
POSTGRES_MODE=managed | external
~~~

The web first-run UI may display the selected database and guidance, but cannot create/replace host containers behind deploy.sh.

## SQLite -> PostgreSQL migration

Provide a controlled deployment workflow when users outgrow SQLite.

Conceptual:

~~~text
./deploy.sh database migrate postgres
~~~

Flow:

1. preflight;
2. verified system/database safety backup;
3. quiesce DB-mutating control-plane work;
4. consistent SQLite snapshot;
5. create target PostgreSQL schema through supported migration/import tooling;
6. copy canonical data preserving IDs/timestamps;
7. validate row counts/relations/critical invariants;
8. switch deployment configuration;
9. start and reconcile;
10. retain the previous SQLite DB through a rollback grace period.

Do not mix database-engine migration silently into a normal software upgrade.

## PostgreSQL -> SQLite migration

Reverse migration may be supported with the same explicit workflow when the current data/workload fits SQLite.

Preflight may reject or strongly warn when:

- database size/load is unsuitable;
- schema/data cannot be represented portably;
- disk space is insufficient;
- backup health is bad.

Canonical IDs/timestamps must be preserved.

## No guessed camera limit

Do not declare SQLite unsuitable based only on a camera-count assumption.

The design-freeze/load benchmark measures:

- 8-camera baseline;
- 16-camera extended target;
- recording-hook/catalog writes;
- Event/Alert writes;
- timeline queries;
- backup/checkpoint behavior;
- SQLITE_BUSY/write latency.

Document measured hardware/config requirements and recommend PostgreSQL only from evidence.

## Health

Useful SQLite diagnostics may include:

- slow-query/retention scan timing and the effective query plan after schema changes;

- database size;
- WAL size;
- recent busy/retry count;
- checkpoint health;
- write latency/backlog when cheaply measurable.

Do not turn the product DB into a telemetry TSDB.

## Testing

CI/integration coverage should include:

- shared model/service tests;
- SQLite migrations and product flows;
- PostgreSQL migrations and product flows;
- backup/restore for both;
- explicit database-engine migration tests.

SQLite remains the primary lightweight test/deployment target, not a second-class development database.

## Acceptance tests

1. Fresh default deployment runs Core with SQLite and no PostgreSQL service.
2. Camera/recording/event/auth/storage features work on SQLite.
3. SQLite WAL/busy behavior survives representative concurrent API/worker load.
4. SQLite backup works during normal operation.
5. PostgreSQL profile/external connection supports the same domain behavior.
6. SQLite -> PostgreSQL migration preserves canonical IDs/timestamps.
7. PostgreSQL -> SQLite path either succeeds safely or refuses with an actionable preflight result.
8. No Redis/Celery requirement appears in either mode.
9. 8-camera baseline SQLite POC passes before design freeze.
10. 16-camera result is documented rather than assumed.

## Invariants

1. SQLite is the default supported production database.
2. PostgreSQL is optional scale-up, not the definition of production.
3. User-visible core features are not intentionally disabled in SQLite mode.
4. Database/network work is not held inside long SQLite transactions.
5. SQLAlchemy/Alembic is the common persistence/migration foundation.
6. Backend-specific behavior remains narrow.
7. Live SQLite files stay on a supported local filesystem.
8. Backup method is backend-specific but product recovery semantics remain unified.
9. Engine migration is explicit and separate from application update.
10. Performance recommendations are measurement-driven.
