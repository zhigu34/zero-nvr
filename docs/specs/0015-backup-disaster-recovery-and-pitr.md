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
