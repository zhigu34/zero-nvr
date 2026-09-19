# Spec 0015 — Backup, Disaster Recovery, PITR, and System Migration

Status: **accepted**

## Goal

Define the complete first-production-release backup and disaster-recovery model for zero-nvr.

Core rule:

> Recording archive protects media. System backup protects the NVR state required to understand, authorize, locate, and recover that media.

A database backup is not a substitute for remote recording archive, and recording archive is not a substitute for database and SecretStore disaster recovery.

## Data-protection layers

```text
1. Recording archive
   local RecordingSegment
       ↓
   archive_remote StorageTarget
       ↓
   verified remote media copy

2. PostgreSQL recovery
   PostgreSQL
       ↓
   mature PostgreSQL backup engine
       ↓
   base/full/differential/incremental + WAL/PITR

3. System/configuration recovery
   metadata + selected non-DB state
       ↓
   SystemBackupSet + manifest
       ↓
   backup-capable StorageTarget

4. Secret/bootstrap recovery
   SecretStore keyring + repository bootstrap data
       ↓
   encrypted RecoveryKit
       ↓
   clean-host recovery
```

## Recording archive remains separate

Recording media is not copied again into every normal system backup.

The canonical media-protection path remains:

```text
local READY
   ↓
archive upload
   ↓
REMOTE_READY verified
   ↓
local purge eligibility
```

System backup protects the database metadata that identifies those remote media objects.

After disaster recovery, PlaybackResolver can reattach to verified remote StorageObjects without downloading all historical video first.

## Media disaster-protection state

For retained media, zero-nvr derives:

```text
local_only
remote_verified
multiple_verified_copies
missing
```

System UI reports remote-protection coverage.

A local-only RecordingSegment is not considered disaster-protected just because its metadata exists in a database backup.

## Backup-capable StorageTarget

StorageTarget may have these roles:

```text
recording_hot
archive_remote
playback_cache
backup
```

One target may hold multiple roles.

Example:

```text
S3 A
  archive_remote
  backup

NAS
  backup

Disk A
  recording_hot
```

Backup and recording objects use separate prefixes/namespaces.

Recommended logical layout:

```text
zero-nvr/
  recordings/
  backups/
    database/
    system/
    recovery/
    manifests/
```

## Backup target capabilities

Not every StorageBackend is suitable for every database-recovery mode.

Conceptual capabilities:

```text
snapshot_backup
pitr_repository
versioned_objects
object_lock
checksum_verify
```

Initial first-release expectation:

- local/POSIX repository can support snapshot and PITR when configured safely;
- S3-compatible target can support snapshot and PITR;
- rclone/OpenList support portable/system snapshot backup through zero-nvr StorageBackend;
- mounted NAS supports PITR only when presented as a reliable supported POSIX repository.

A snapshot-only target must not be shown as PITR-capable.

## PostgreSQL backup engine

Use a mature PostgreSQL backup engine rather than implementing WAL archive semantics in application code.

Initial first-release backend:

```text
PgBackRestBackupBackend
```

Responsibilities delegated to the backup engine:

- full backup;
- differential/incremental backup;
- WAL archive push/get;
- backup-repository consistency;
- restore;
- point-in-time recovery;
- backup verification/information.

zero-nvr owns policy, orchestration, authorization, UI, product manifests, health, and clean-host recovery workflow.

## Database recovery modes

Support:

```text
latest_consistent
point_in_time
selected_backup
```

Example point in time:

```text
2026-09-19 14:32:10 UTC
```

PITR uses canonical UTC internally. UI input/output follows Spec 0009 timezone handling.

## BackupPolicy

```text
BackupPolicy
  id
  name
  enabled

  backup_target_id

  database_backup_enabled
  database_mode             pitr | snapshot_only

  full_schedule
  differential_schedule
  snapshot_schedule

  pitr_enabled
  wal_archive_enabled

  retention_daily
  retention_weekly
  retention_monthly
  minimum_recovery_days

  verify_after_backup
  periodic_restore_test_enabled
  periodic_restore_test_schedule

  portable_snapshot_enabled

  created_at
  updated_at
```

Schedules and retention are configurable.

A reasonable product default can use daily base/full backup plus continuous WAL archive, but these are defaults rather than domain constants.

## BackupSet

```text
BackupSet
  id
  backup_policy_id
  backup_target_id

  type                    database | system_snapshot | portable
  state                   preparing | uploading | verifying | ready | failed | expired

  started_at
  completed_at

  base_time
  recoverable_until

  app_version
  schema_revision
  postgres_version
  instance_id

  manifest_object_key
  size_bytes
  checksum

  verification_state
  last_verified_at

  error_code
  sanitized_error

  created_at
  updated_at
```

Continuous WAL archive is repository state and does not require one BackupSet row per WAL object.

## BackupManifest

Every system snapshot has a versioned manifest.

```text
format_version
backup_set_id
instance_id
created_at

zero_nvr_version
database_schema_revision
postgres_version

database_backup_reference
pitr_repository_reference

secretstore_key_ids_required
recovery_capsule_reference

storage_targets
recording_archive_summary
media_protection_summary

included_components
checksums
```

The manifest never stores plaintext credentials.

## Automatic system backup contents

Normal automatic system backup includes or references:

- PostgreSQL recovery state;
- ordinary configuration;
- Camera/Recording/Event/Alert/User/Role/Audit metadata;
- RecordingSegment and StorageObject metadata;
- SecretRecord ciphertext and wrapped DEKs;
- version/schema data;
- non-secret restore metadata;
- BackupManifest;
- encrypted recovery capsule when configured.

It does not duplicate all recording media.

## Reconstructable runtime state

Derived/runtime state is recreated rather than treated as precious backup content.

Examples:

```text
ZLMediaKit generated runtime config
worker transient state
playback cache
tmpfs prebuffer
derived thumbnails/cache where reproducible
```

Only non-reconstructable operator-managed state belongs in the system backup.
