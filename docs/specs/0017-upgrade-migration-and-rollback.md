# Spec 0017 — Upgrade, Schema Migration, Database Migration, and Rollback

Status: **accepted**

## Goal

Define the complete first-production-release upgrade and rollback model for zero-nvr.

Core rule:

> Application version changes are reversible where practical; data changes are protected by verified backups and explicit compatibility gates.

An upgrade must never silently leave zero-nvr running with an application/schema/database combination that has not passed compatibility checks.

## Upgrade scope

An upgrade may change several independently versioned components:

```text
zero-nvr web
zero-nvr api
zero-nvr worker
database schema
ZLMediaKit
FFmpeg tooling
Litestream
pgBackRest
optional HIK/WVP/HA integration packages
```

The product upgrade workflow owns compatibility across these components.

## Release identity

Every release has immutable metadata:

```text
version
release_channel
build_id
git_revision
published_at
minimum_schema_revision
target_schema_revision
minimum_supported_source_version
database_compatibility
component_versions
image/package digests
release_notes_reference
migration_notes
rollback_class
```

Do not deploy mutable `latest` as the authoritative rollback identity.

Container images/packages are pinned by version/digest.

## Release channels

First-release supported channels:

```text
stable
preview
```

Stable is default. Preview is an explicit administrator opt-in.

The update checker may report availability, security relevance, required downtime class, database migration class, and rollback implications before installation.

## Update policy

System settings support:

```text
check_for_updates
release_channel
update_mode            notify_only | manual | scheduled
maintenance_timezone
maintenance_schedule
automatic_security_updates
```

Recommended default is `notify_only` or explicit manual installation.

Scheduled automatic upgrade is supported but must still run all preflight/backup gates and abort safely when they fail.

## UpgradePlan

Before mutation, zero-nvr builds a persisted plan.

```text
UpgradePlan
  id
  source_version
  target_version
  source_schema_revision
  target_schema_revision
  database_engine
  status
  rollback_class
  requires_maintenance
  requires_database_backup
  requires_recovery_kit_current
  estimated_steps
  preflight_result
  created_by
  created_at
  started_at
  completed_at
```

Upgrade execution is resumable/diagnosable rather than a single opaque shell command.

## Preflight

Preflight occurs before stopping the working version.

At minimum check:

- target release metadata/signature/digest validity;
- current version is a supported upgrade source;
- database engine and version are supported;
- current schema revision is known;
- required migrations exist for SQLite and PostgreSQL;
- free space for image/package pull, staging, database snapshot, and temporary migration files;
- backup target health where a safety backup is required;
- RecoveryKit current/stale state;
- SecretStore keyring health;
- no unfinished restore/database migration/key rotation that conflicts with upgrade;
- StorageTarget/media health sufficient for safe maintenance;
- external component compatibility;
- migration dry checks where supported.

Preflight failure leaves the current system unchanged.

## Mandatory pre-upgrade safety point

For an upgrade that changes database schema or other non-reconstructable state:

```text
create safety backup
      ↓
verify backup
      ↓
record backup_set_id on UpgradePlan
      ↓
only then allow mutation
```

SQLite uses a verified Online Backup snapshot and, when configured, confirms Litestream replica health.

PostgreSQL uses a verified pgBackRest backup/recovery point and WAL archive health.

A stale/unverified backup does not satisfy the automatic rollback safety gate.

## Upgrade maintenance modes

UpgradePlan classifies work into:

```text
online
control_plane_maintenance
full_maintenance
```

### Online

No incompatible schema or runtime changes. Rolling process restart may be enough.

### Control-plane maintenance

API mutations/workers pause while media runtime may continue temporarily when safe.

### Full maintenance

Recording/media control is intentionally stopped because schema/runtime/component changes cannot be safely mixed.

The UI shows the expected impact before the administrator starts the upgrade.

## Recording behavior during upgrade

Do not promise zero recording interruption for every upgrade.

Where architecture permits:

- ZLMediaKit proxy/live runtime may stay up during a control-plane restart;
- an already running FFmpeg/ZLM recording process may continue only if its metadata/finalization contract remains compatible;
- new recording intents/configuration changes are paused while control plane is in maintenance;
- pending media finalization is reconciled after restart.

For upgrades that cannot preserve this safely, use full maintenance and expose the resulting recording gap explicitly.

Correctness is preferred over hidden partial recording.

## Database schema migration strategy

Use Alembic as the schema migration coordinator, with backend-specific implementations/tests for SQLite and PostgreSQL.

Prefer expand/contract:

```text
Release N
  add new nullable/new structures
  old readers/writers still work

Release N+1
  backfill / dual-read-write if required

Release N+2
  remove obsolete structure after compatibility window
```

This reduces application-version/schema lockstep and improves rollback safety.

## Migration classes

Every migration is classified:

```text
A: additive / backward compatible
B: data backfill or transform, old version still compatible
C: destructive/incompatible, rollback requires database restore
```

UpgradePlan displays the highest migration class.

Class C requires a verified pre-upgrade recovery point and explicit maintenance.

## SQLite schema changes

SQLite migrations may require table rebuild/copy for operations that are simple ALTER operations on PostgreSQL.

Rules:

- use Alembic batch/table-rebuild patterns where required;
- create work files on the same protected local filesystem;
- verify resulting schema and foreign-key/integrity checks;
- never mutate the only live SQLite file without a verified pre-upgrade snapshot;
- checkpoint/coordinate WAL before operations that require exclusive database replacement;
- atomic file replacement is used only after validation.

## PostgreSQL schema changes

PostgreSQL migrations should avoid long blocking DDL where practical.

Rules:

- create indexes concurrently where semantics allow;
- use bounded lock/statement timeouts for migration steps where appropriate;
- split large backfills from short schema transactions;
- record progress for restartable long data migrations;
- do not hold application-wide transactions around external work.

## DataMigrationJob

Large data transformations are explicit durable jobs rather than hidden startup work.

```text
DataMigrationJob
  id
  upgrade_plan_id
  migration_id
  state
  cursor
  processed_count
  error_count
  started_at
  updated_at
  completed_at
```

The application can expose progress and safely resume idempotent batches.

## Startup compatibility gate

Every API/worker process checks:

```text
application version
database engine
database schema revision
migration state
instance compatibility marker
```

Then it either:

```text
start normally
start maintenance/recovery mode
refuse normal startup with actionable diagnostics
```

Never automatically run unknown/destructive migrations merely because a new container started.

## Upgrade execution

Conceptual flow:

```text
check update
   ↓
build UpgradePlan
   ↓
preflight
   ↓
verified safety backup
   ↓
enter required maintenance level
   ↓
pull/stage target artifacts
   ↓
run schema/data migrations
   ↓
start target services
   ↓
health/readiness checks
   ↓
media/storage/database reconciliation
   ↓
commit upgrade
   ↓
leave maintenance
```

The source version artifacts/config remain available until the upgrade is committed and rollback retention expires.

## Post-upgrade validation

Required validation includes:

- database schema revision and integrity;
- SecretStore decrypt self-test;
- camera/runtime inventory load;
- ZLMediaKit health;
- recorder/reconciliation health;
- StorageTargets;
- alert/notification worker;
- backup engine;
- live/playback smoke checks where automated;
- background-job queue consistency.

Failure before commit invokes rollback policy.

## Rollback classes

Rollback is not one mechanism.

### Binary/config rollback

For no-schema/additive-compatible changes:

```text
stop target version
restore previous compose/image/package version
start previous version
health check
```

No database restore is needed if schema remains backward compatible.

### Application rollback with compatible schema

If the target added structures but the previous application remains schema-compatible, keep the migrated database and restore the previous application version.

### Recovery-point rollback

For destructive/incompatible Class C migration:

```text
stop target version
restore pre-upgrade database recovery point
restore matching app/config if needed
run media/storage reconciliation
start previous version
```

Do not rely on a hand-written `downgrade()` migration to reverse irreversible data loss.

## Automatic rollback

Automatic rollback is allowed only when the plan has an unambiguous verified rollback path.

Examples:

- target service fails health check before commit;
- migration step fails before incompatible commit;
- startup compatibility gate rejects target.

If rollback requires selecting among multiple recovery points or risks discarding post-upgrade accepted writes, zero-nvr stops in maintenance/recovery mode and requires explicit administrator action.

## Commit point

An upgrade is not committed when containers merely start.

Commit requires:

```text
target services ready
database/schema verified
required migrations complete
core health checks pass
no critical reconciliation failure
```

Before commit, user mutations remain limited according to maintenance mode so rollback does not silently lose newly accepted writes.

## Upgrade history

```text
UpgradeHistory
  id
  upgrade_plan_id
  source_version
  target_version
  source_schema_revision
  target_schema_revision
  database_engine
  safety_backup_set_id
  result
  rollback_result
  started_at
  committed_at
  completed_at
  error_code
  sanitized_error
```

History is visible in System > Updates.

## Cross-database migration is separate

SQLite ↔ PostgreSQL migration from Spec 0016 is not silently bundled into a normal software update.

Normal upgrade preserves the selected database engine.

A database-engine migration is its own guided DatabaseMigrationPlan with separate backup, validation, cutover, and rollback.

This avoids debugging software-version change and database-engine change at the same time.

## DatabaseMigrationPlan

```text
DatabaseMigrationPlan
  id
  source_engine
  target_engine
  source_schema_revision
  target_schema_revision
  source_version
  status
  safety_backup_set_id
  validation_summary
  cutover_at
  rollback_deadline
  created_by
  created_at
  completed_at
```

Cross-engine migration preserves canonical IDs/timestamps and validates critical counts/relations before cutover.

## Database migration cutover

Conceptual flow:

```text
preflight
   ↓
verified safety backup
   ↓
maintenance mode
   ↓
freeze DB-mutating workers
   ↓
final consistent source snapshot
   ↓
copy/transform into target schema
   ↓
validate
   ↓
switch active DB configuration
   ↓
start/reconcile
   ↓
commit cutover
```

Before commit, failure returns to the untouched source database.

After commit, the old database is retained read-only for a configurable rollback grace period rather than immediately deleted.

## PostgreSQL to SQLite guard

Reverse migration performs workload and compatibility preflight from Spec 0016.

If current sustained workload is above configured safe thresholds, UI warns and may require explicit override, but it does not invent a reduced-feature SQLite mode.

## Upgrade and backup interaction

Upgrade safety backups are tagged:

```text
reason = pre_upgrade
source_version
target_version
upgrade_plan_id
```

They follow a protected short-term retention policy and cannot be purged until the rollback window closes or the administrator explicitly releases them.

## Media objects across rollback

Media written around upgrade/rollback may exist outside the restored metadata point.

Use the same non-destructive reconciliation principle as Spec 0015:

```text
unknown/newer media
   ↓
quarantine/reconcile
   ↓
import/relink when identity is proven
```

Never auto-delete recording files solely because a database rollback no longer references them.

## Component update independence

Some components may be updated independently when compatibility metadata permits.

Examples:

- FFmpeg security/bugfix image;
- ZLMediaKit patch;
- Litestream/pgBackRest patch;
- Home Assistant integration package.

Compatibility matrix and pinned versions remain part of the zero-nvr release manifest.

Unsupported independent component drift is surfaced as health/configuration warning.

## Permissions

Initial permissions:

```text
update.view
update.manage
database.migrate
```

Installing an update, rolling back, changing release channel, or performing cross-database migration requires recent re-authentication and MFA when enabled.

## Audit

Audit includes:

```text
update.channel_changed
update.plan_created
update.started
update.completed
update.failed
update.rollback_started
update.rollback_completed
database.migration_started
database.migration_cutover
database.migration_rolled_back
```

Audit never records secret values.

## Alerts and health

Health/alerts include:

```text
update.available
update.preflight_failed
update.failed
update.rollback_failed
migration.failed
migration.incomplete
database.compatibility_error
component.version_mismatch
```

A failed update notification never alters recording state by itself.

## UI

System > Updates:

```text
Current version
Release channel
Available version
Release notes
Migration class
Expected maintenance impact
Safety backup status
RecoveryKit status

[Run preflight]
[Update]
[Rollback] when valid
```

System > Database:

```text
Current: SQLite / PostgreSQL
Health/load

[Migrate to PostgreSQL]
[Migrate to SQLite] when preflight allows
```

Upgrade progress displays named steps and actionable failure diagnostics.

## Acceptance tests

1. no-schema patch upgrade performs preflight, switches artifacts, validates, and commits;
2. SQLite additive migration upgrades and binary-rolls back without DB restore;
3. SQLite incompatible migration failure restores verified pre-upgrade snapshot when required;
4. PostgreSQL migration failure uses pgBackRest recovery point when schema is incompatible;
5. target starts but fails health check before commit: automatic rollback succeeds when unambiguous;
6. Class C upgrade cannot start without verified safety backup;
7. application refuses normal startup against unsupported newer schema;
8. upgrade rollback preserves unknown/newer media for reconciliation instead of deleting it;
9. SQLite to PostgreSQL migration failure before cutover leaves original SQLite authoritative;
10. successful DB migration preserves Camera/Recording/Event IDs and retains old DB for rollback grace period;
11. PostgreSQL to SQLite preflight warns on sustained unsafe workload;
12. update attempt while restore/key rotation/database migration is active is blocked;
13. scheduled auto-update aborts safely when preflight/backup gates fail;
14. upgrade/rollback actions are permission-gated and audited.

## Invariants

1. Upgrade preflight happens before mutating the working installation.
2. Schema/non-reconstructable changes require a verified pre-upgrade safety point.
3. SQLite and PostgreSQL both have tested schema-upgrade and rollback paths.
4. Migrations are explicitly classified by backward compatibility/destructiveness.
5. Destructive data rollback uses a verified recovery point rather than pretending all migrations are logically reversible.
6. Normal startup is gated by application/database/schema compatibility.
7. An upgrade is committed only after migrations and core health checks pass.
8. Automatic rollback occurs only when lossless/unambiguous.
9. Cross-database migration is a separate operation from normal software update.
10. Failed pre-cutover DB migration leaves the source database authoritative.
11. Old database/source artifacts survive a rollback grace period after successful cutover.
12. Database rollback never causes automatic deletion of extra recording media.
13. Update and database-migration operations are permission-gated, re-authenticated, MFA-aware, and audited.
14. Maintenance impact is shown honestly; zero recording downtime is not falsely guaranteed.
15. Non-obvious upgrade/schema/rollback/cutover behavior requires comments per Development Guidelines.