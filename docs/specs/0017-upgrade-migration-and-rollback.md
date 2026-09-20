# Spec 0017 — Upgrade, Schema Migration, Database Migration, and Rollback

Status: **accepted**

## Goal

Define a safe V1 upgrade model that matches the deployment architecture.

Core rule:

> V1 upgrade authority is the deployment interface: `deploy.sh + .env + Docker Compose`. The web application may report version/update information, but it does not need to become a self-updating orchestration platform.

See [Project Baseline](../PROJECT_BASELINE.md) and [Deployment](../DEPLOYMENT.md).

## Upgrade authority

Primary command:

```text
./deploy.sh update
```

Optional explicit target version:

```text
./deploy.sh update <version>
```

The script coordinates mature tools:

- Docker Compose for image/service lifecycle;
- Alembic for schema migration;
- SQLite Online Backup or pg_dump for database safety points;
- restic for protected backup storage/verification;
- application health/readiness endpoints;
- adapter compatibility checks.

Do not create a second in-app deployment engine merely to duplicate Compose.

## V1 UI responsibility

System > Updates may show:

- current zero-nvr version;
- current schema revision;
- bundled/recommended component versions;
- available release information when an update source is configured;
- whether a migration is required;
- current compatibility/health warnings;
- the exact deploy.sh command to run.

V1 does **not** require:

- automatic scheduled application upgrades;
- the API controlling Docker;
- mounting the Docker socket into zero-nvr;
- a complex persisted UpgradePlan workflow;
- browser-initiated host mutation.

These may be reconsidered later only with a clear operational need and ADR.

## Release identity

Production releases use immutable version identities.

Track:

```text
version
git_revision/build_id
schema_revision
component compatibility
image digest/tag
release notes
migration notes
rollback notes
```

Do not depend on mutable `latest` as the only rollback identity.

## Supported components

A release manifest should pin or declare compatible versions for the components it owns/depends on, including:

- zero-nvr image;
- ZLMediaKit;
- FFmpeg/ffprobe toolchain embedded in the zero-nvr image;
- rclone/restic embedded tool versions;
- optional managed Frigate/OpenList/Mosquitto/PostgreSQL versions where applicable.

External-mode services are checked for compatibility where the integration requires a minimum version.

## Preflight

Before mutating a working installation, `deploy.sh update` checks as applicable:

- requested version exists/is valid;
- current source version is supported;
- current schema revision is known;
- migration path exists;
- .env/deployment configuration validates;
- required secrets exist;
- sufficient free space exists for new image + safety backup + temporary migration files;
- database is reachable;
- required pre-upgrade backup target is usable;
- core component compatibility is acceptable;
- no active restore/database migration conflicts with the update.

Preflight failure leaves the running installation unchanged.

## Pre-upgrade safety point

A schema-changing or otherwise non-trivial upgrade must create and verify a safety backup before migration.

### SQLite

```text
SQLite Online Backup
-> restic
-> verify snapshot metadata
```

### PostgreSQL

```text
pg_dump
-> restic
-> verify snapshot metadata
```

The backup records at least:

- source version;
- target version;
- schema revision;
- database engine;
- creation time;
- restic snapshot identity.

If the required safety point fails, abort the upgrade.

## Upgrade execution

Conceptual flow:

```text
preflight
-> create/verify safety backup when required
-> pull/stage target images
-> stop only services that must stop
-> run Alembic migration in controlled mode
-> start target services
-> readiness/health checks
-> recording/storage reconciliation
-> mark deployment successful
```

Where safe, ZLMediaKit may remain running during control-plane updates so an already-running recording is not deliberately interrupted.

Do not guarantee zero recording gaps for migrations that genuinely require full maintenance.

## Database migration strategy

Use SQLAlchemy 2.x models and Alembic migrations for both SQLite and PostgreSQL.

Prefer additive/backward-compatible changes where practical.

Migration classes:

```text
A = additive/backward compatible
B = data transform/backfill with compatible rollback path
C = destructive/incompatible; rollback requires restoring safety backup
```

Class C requires explicit maintenance and verified safety backup.

## Startup compatibility gate

API and worker check:

- application version;
- database engine;
- schema revision;
- migration state.

They either:

```text
start normally
or
refuse normal startup with actionable diagnostics
```

Do not silently run unknown destructive migrations merely because a container restarted.

Routine safe migrations may be invoked explicitly by deploy.sh.

## SQLite migration rules

- use Alembic batch/table-rebuild patterns when required;
- verify foreign keys/integrity after migration;
- never treat the only live DB file as the rollback copy;
- create a verified Online Backup before incompatible work;
- coordinate/checkpoint WAL when operations require file replacement.

## PostgreSQL migration rules

- avoid unnecessarily long blocking DDL;
- use bounded lock/statement timeouts where appropriate;
- split large backfills into restartable batches if needed;
- do not hold a database transaction around external network/file work.

## Rollback

### Binary/config rollback

When schema remains compatible:

```text
stop target zero-nvr services
-> restore previous pinned image/config version
-> start
-> health check
```

### Recovery-point rollback

For an incompatible migration:

```text
stop target control-plane services
-> restore verified pre-upgrade DB safety point
-> restore matching application/config version
-> start
-> run media/storage reconciliation
-> health check
```

Do not rely on hand-written downgrade migrations to reverse irreversible data loss.

## Failure before commit

If migration/startup/health validation fails before successful completion:

- leave useful logs and diagnostics;
- automatically roll back only when the rollback path is unambiguous and non-lossy;
- otherwise stop in a documented recovery state and instruct the operator to run the rollback/recovery deploy.sh path.

Do not keep repeatedly restarting an incompatible version.

## Media safety across rollback

Recording media is never deleted merely because database rollback restores older metadata.

After rollback:

```text
scan/reconcile known media
-> relink/import when identity is proven
-> surface unresolved media
```

The recording filesystem remains a source for recovery reconciliation.

## Database-engine migration is separate

SQLite <-> PostgreSQL conversion is **not** bundled into normal `deploy.sh update`.

Use a separate controlled command/workflow, for example:

```text
./deploy.sh database migrate postgres
./deploy.sh database migrate sqlite
```

Exact CLI syntax may evolve, but the operation remains distinct.

Required behavior:

- verified safety backup;
- freeze DB-mutating tasks for cutover;
- copy/transform;
- validate IDs/counts/relations;
- switch configuration;
- health/reconciliation;
- retain old database for rollback grace period.

## Component compatibility

Adapters expose enough version information to diagnose incompatibility.

Examples:

```text
ZLMediaKit: supported
Frigate: unsupported version
OpenList: unreachable
PostgreSQL: external / supported
```

Unsupported component drift becomes capability health/configuration warning rather than mysterious downstream API errors.

## deploy.sh commands

The deployment interface should converge on:

```text
./deploy.sh install
./deploy.sh update [version]
./deploy.sh status
./deploy.sh doctor
./deploy.sh feature enable <name>
./deploy.sh feature disable <name>
./deploy.sh backup
./deploy.sh restore
./deploy.sh rollback [version]
```

The implementation may add subcommands as needed, but V1 should remain understandable and shell-operable.

## Audit and history

The application may persist product-visible upgrade events when the API/database is available:

```text
system.update_started
system.update_completed
system.update_failed
system.rollback_completed
database.migration_completed
```

deploy.sh itself also writes operator-readable logs.

A separate heavyweight UpgradePlan table is not required for V1.

## Acceptance tests

1. No-schema patch update:
   - preflight passes;
   - new image starts;
   - previous pinned version remains known for rollback.

2. SQLite schema update:
   - verified Online Backup/restic safety point is created;
   - Alembic migration succeeds;
   - application starts with expected schema.

3. Failed SQLite incompatible migration:
   - installation does not continue in half-migrated normal mode;
   - recovery-point rollback restores service.

4. PostgreSQL update:
   - pg_dump/restic safety point is created when required.

5. ZLM remains running during a control-plane-only update where compatible:
   - existing recording is not deliberately stopped;
   - catalog is reconciled afterward.

6. Health check fails after new version starts:
   - unambiguous rollback restores the previous working application.

7. Application encounters unsupported newer schema:
   - startup is refused with actionable diagnostics.

8. Database rollback:
   - newer recording media is not auto-deleted.

9. External component has unsupported version:
   - compatibility warning is explicit.

10. `latest` changes upstream:
   - deployment/rollback still uses explicit known version identity.

## Invariants

1. deploy.sh is the V1 host-mutation/upgrade authority.
2. zero-nvr does not need Docker-socket access to update itself.
3. Preflight runs before destructive mutation.
4. Schema/non-reproducible changes require a verified safety backup.
5. Alembic is the schema migration coordinator for SQLite and PostgreSQL.
6. Normal startup never silently performs unknown destructive migrations.
7. Rollback never auto-deletes extra recording media.
8. Cross-database migration is separate from normal software update.
9. Component compatibility is explicit and diagnosable.
10. Automatic scheduled self-update is not a V1 requirement.
