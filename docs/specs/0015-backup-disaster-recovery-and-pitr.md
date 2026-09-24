# Spec 0015 — Backup, Disaster Recovery, and System Migration

Status: **accepted**

## Goal

Define a complete but lightweight V1 backup/restore model.

Core rule:

> Recording archive protects video media. System backup protects the product state and secrets required to operate zero-nvr and understand that media.

V1 must be restorable without introducing a second database replication stack as a mandatory dependency.

See [Project Baseline](../PROJECT_BASELINE.md).

## V1 backup architecture

### SQLite

```text
SQLite
-> SQLite Online Backup API
-> consistent backup file
-> restic
-> backup repository
```

### PostgreSQL

```text
PostgreSQL
-> pg_dump
-> consistent dump
-> restic
-> backup repository
```

### restic owns

- repository encryption;
- deduplication;
- repository snapshots;
- retention primitives;
- repository integrity checking;
- remote repository transport supported by restic.

### zero-nvr owns

- scheduling;
- backup scope;
- metadata/manifest;
- health/status;
- invoking database-native backup;
- invoking restic;
- verification policy;
- restore orchestration;
- UI/API state;
- audit.

## Optional advanced recovery

Litestream, pgBackRest, WAL/PITR, filesystem snapshots, and platform-native replication may be supported later or documented as advanced integrations.

They are **not** V1 release gates and are not mandatory runtime dependencies.

Adding one as a product-managed capability requires an ADR explaining why the lightweight baseline is insufficient.

## Recording archive is separate

Normal recording media is not copied into every system backup.

Recording lifecycle remains:

```text
local recording
-> rclone archive
-> verified remote RecordingLocation
```

System backup preserves the metadata required to locate and interpret those RecordingLocations.

A database backup does not protect a local-only video file from disk loss.

## Backup scope

Non-reproducible state includes, as applicable:

- SQLite backup or PostgreSQL dump;
- Camera configuration;
- stream bindings;
- users/roles/permissions;
- RecordingSegment/RecordingLocation catalog;
- Event/Alert state;
- storage/retention policies;
- notification/integration configuration;
- AuditLog according to retention policy;
- deployment/product settings;
- encrypted credentials/SecretStore state;
- master-key/bootstrap recovery material;
- rclone configuration/secrets required by configured remotes;
- backup manifest and application/schema version.

## Excluded data

Disposable or reproducible data should not be included by default:

- recording video files already governed by recording/archive policy;
- thumbnails;
- export cache;
- playback cache;
- rclone cache;
- temporary files;
- Timeline/Gap projections;
- in-memory health state;
- regenerated frontend assets;
- container images.

Users may independently back up recording volumes at the storage-platform layer if desired.

## RecoveryKit

A restore is useless if encrypted camera/storage credentials cannot be decrypted.

The documented RecoveryKit must preserve the bootstrap material required to recover secrets, for example:

```text
ZERO_NVR_SECRET_KEY or equivalent master/bootstrap key
backup repository bootstrap details
required repository password/key material
deployment identity/version metadata
restore instructions
```

RecoveryKit handling must avoid casually writing plaintext secrets into application logs or normal downloadable configuration exports.

The authenticated web workflow generates a password-encrypted RecoveryKit artifact
only on explicit administrator request. V1 uses scrypt-derived AES-256-GCM and
never stores the download passphrase. The server persists only non-secret
generation metadata/fingerprint so the UI can report whether the last generated
kit is current or stale after keyring, backup-policy, database, or application
version changes. The encrypted payload carries a minimal clean-host bootstrap
environment plus the selected backup repository bootstrap credentials.

## Backup run model

A lightweight product history may track:

```text
BackupRun
  id
  started_at
  completed_at
  status
  database_engine
  app_version
  schema_revision
  restic_snapshot_id
  reason
  verification_status
  error_code
```

The database itself is not the only source of proof; restic snapshot identity and verification results must be checked during restore.

## Backup reasons

Useful reasons:

```text
scheduled
manual
pre_upgrade
pre_restore
pre_database_migration
```

Pre-upgrade/pre-migration backups may use a protected retention policy until the rollback window closes.

## Scheduling

Huey schedules product backup tasks.

Suggested defaults are configurable and should be conservative for small systems.

Example:

```text
database/system backup: daily
restic repository check: periodic, lower frequency
retention/prune: scheduled outside busy periods
```

Do not perform expensive full checks on every small backup unless needed.

## Verification

A successful subprocess exit alone is not enough.

V1 should record:

- database backup/dump completed;
- restic snapshot created;
- expected manifest exists;
- repository is accessible;
- most recent integrity-check status;
- restore test status when an administrator performs one.

Periodic `restic check` is part of the supported operating model.

## deploy.sh interface

Backup/restore is also available from the deployment interface:

```text
./deploy.sh backup
./deploy.sh restore
```

The web UI may schedule and inspect backups, but disaster recovery must not depend on the web application already being healthy.

This allows recovery from a clean host or broken control plane.

## Restore flow

Conceptual clean-host restore:

```text
install compatible zero-nvr release
-> provide RecoveryKit/bootstrap secret
-> connect/open restic repository
-> select backup snapshot
-> restore backup payload to staging
-> verify manifest/version/schema compatibility
-> restore SQLite backup or PostgreSQL dump
-> restore required configuration/secret material
-> start zero-nvr services
-> run schema compatibility/migrations when explicitly supported
-> reconcile recording/storage catalog
-> health validation
```

Do not overwrite the current installation blindly. Restore should stage and validate before destructive replacement where practical.

## Recording media after restore

Media may have changed after the restored database point.

Therefore:

- do not delete media merely because the restored DB does not reference it;
- reconcile known recording roots/remotes;
- import/relink only when identity can be proven;
- surface unresolved orphan/missing media for diagnosis.

System restore must be non-destructive toward valid recordings.

## Configuration export is not backup

A user-facing configuration export may contain portable non-sensitive or selectively encrypted settings for migration.

It is distinct from disaster backup.

Configuration export may include:

- camera definitions without plaintext secrets;
- recording policies;
- retention policies;
- alert policies;
- selected product settings.

It does not claim to preserve the complete database, audit/history, credential keyring, or recording catalog.

## Cross-database migration

SQLite <-> PostgreSQL migration is a separate controlled operation.

It must:

- take a verified safety backup;
- stop/freeze DB-mutating work during cutover;
- preserve canonical IDs/timestamps;
- validate row counts and critical relations;
- retain the old database for a rollback grace period;
- reconcile media after cutover.

Do not combine database-engine migration implicitly with a normal application upgrade.

## Backup repository choices

restic may target a supported repository backend appropriate to the deployment.

The exact repository can be local, NAS, SFTP, S3-compatible, or another restic-supported backend.

Recording archive and system backup may use the same physical provider but should use separate namespaces/credentials/retention semantics where practical.

## Failure behavior

Backup failure:

- does not stop recording;
- creates a degraded/critical backup capability state depending on policy;
- raises Alert/Notification according to configured rules;
- preserves the previous valid backup;
- never causes recording retention to assume that video archive is protected.

## Acceptance tests

1. SQLite backup:
   - Online Backup produces a restorable database while the system is running.

2. PostgreSQL backup:
   - pg_dump produces a restorable dump.

3. restic:
   - backup snapshot is created and listed;
   - periodic check can verify repository integrity.

4. secret recovery:
   - clean restore can decrypt configured credentials using RecoveryKit material.

5. clean-host restore:
   - zero-nvr starts with restored users/cameras/policies/catalog.

6. media reconciliation:
   - media newer than the DB backup is not auto-deleted.

7. disposable cache:
   - restore succeeds without thumbnail/export/playback cache.

8. backup failure:
   - recording continues;
   - backup health becomes degraded and retryable.

9. pre-upgrade backup:
   - deploy.sh refuses a schema-changing upgrade when its required safety backup fails.

10. configuration export:
   - export/import remains distinct from full disaster restore.

## Invariants

1. V1 backup uses database-native consistent backup plus restic.
2. Recording archive and system backup are separate responsibilities.
3. Secret bootstrap/recovery material is part of disaster-recovery planning.
4. Disposable caches are not required for a successful restore.
5. Backup failure never stops healthy local recording.
6. A restore never auto-deletes recording media solely because restored metadata is older.
7. PITR/replication products are optional advanced capabilities, not mandatory V1 dependencies.
8. Disaster recovery remains possible from deploy.sh without relying on an already-working web UI.
