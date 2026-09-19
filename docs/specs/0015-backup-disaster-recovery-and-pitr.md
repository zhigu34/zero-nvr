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

## Keyring recovery

SecretRecord ciphertext in PostgreSQL cannot be recovered without the matching SecretStore KEK/keyring.

The keyring is protected independently from the database.

Never store the plaintext keyring beside the database backup in the same ordinary backup repository.

## RecoveryKit

The first production release provides an operator-controlled encrypted RecoveryKit.

Conceptual contents:

```text
format_version
instance_id

backup repository identity
backup target endpoint metadata
backup target credential package when required

SecretStore keyring package
key ids

recovery metadata
checksums
```

RecoveryKit is encrypted by an operator-controlled recovery passphrase/key.

Use a memory-hard KDF such as Argon2id plus authenticated encryption.

The plaintext recovery passphrase/key is never stored in PostgreSQL.

## Backup-target credential bootstrap

A true disaster-recovery target must be accessible before the lost database/SecretStore is restored.

Supported credential sources:

```text
ambient/instance IAM
bootstrap secret file
operator-entered credential
encrypted credential package in RecoveryKit
```

For S3 deployments with platform IAM, temporary/ambient credentials are preferred.

For self-hosted static credentials, RecoveryKit provides the portable recovery path.

A backup target whose only usable credential lives inside the lost SecretStore is not considered fully disaster-recoverable.

## RecoveryKit lifecycle

RecoveryKit must be regenerated or marked stale when any recovery-critical material changes, including:

- SecretStore keyring rotation;
- disaster-recovery backup-target credentials;
- repository identity/location;
- encryption format version.

UI shows:

```text
RecoveryKit
  status: current | stale | missing
  generated_at
  required_key_ids
  repository
```

The operator can download a current encrypted RecoveryKit after re-authentication.

RecoveryKit download is audited.

## Portable encrypted system backup

In addition to scheduled backups, zero-nvr supports a self-contained portable migration backup.

Use cases:

```text
move to a new server
offline disaster-recovery copy
manual before major upgrade
lab/test restore
```

The portable backup includes:

- database snapshot;
- configuration;
- SecretStore keyring material;
- recoverable managed secrets;
- manifest/version metadata.

It excludes recording media by default.

The whole portable artifact is independently encrypted using an operator-supplied recovery passphrase/key.

No plaintext intermediate secret archive is written to persistent disk.

## Recording-media inclusion

Portable/system backup does not include video by default.

An optional selected-media export may exist for a bounded range/camera, but it is an export/archive operation rather than normal system backup.

For full media disaster protection, use verified remote recording archive.

## Backup verification levels

Backup success has multiple states:

```text
created
uploaded
verified
restore_tested
```

"Uploaded" alone is not considered sufficient.

### Artifact verification

Verify where supported:

- object existence;
- size;
- checksum/digest;
- manifest consistency;
- expected database backup metadata;
- required recovery key IDs.

### Restore test

First production release supports periodic automated restore testing.

The test restores into an isolated temporary PostgreSQL instance/environment and verifies at least:

- PostgreSQL starts;
- expected schema revision is present;
- core tables are readable;
- BackupManifest matches restored database identity;
- SecretRecord/keyring compatibility can be validated without exposing secrets;
- a sample of StorageObject references can be resolved/checked.

Restore testing must not modify the production database.

## Backup health

System health exposes:

```text
last_successful_backup
last_verified_backup
last_restore_test
pitr_wal_archive_lag
oldest_recoverable_time
newest_recoverable_time
backup_target_health
recovery_kit_status
local_only_media_bytes
remote_protected_media_bytes
```

Health degrades when backup age, WAL archive lag, failed verification, stale RecoveryKit, or target failures exceed policy thresholds.

## Backup retention

Backup retention is separate from recording retention.

Policy may express:

```text
daily copies
weekly copies
monthly copies
minimum PITR recovery window
portable backups pinned by user
```

Example defaults may be:

```text
daily   14
weekly   8
monthly 12
```

but these remain configurable product defaults.

Retention never deletes the only base backup still required by unexpired WAL/PITR history.

The PostgreSQL backup engine's repository-retention rules remain authoritative for repository consistency, while zero-nvr presents policy and status.

## Backup deletion protection

Backup deletion is high risk.

Before deleting a BackupSet/repository generation:

- verify retention dependency;
- verify it is not the only usable recovery point;
- verify PITR chain requirements;
- respect user pin/lock;
- record AuditEvent.

A user-facing delete action must not directly remove arbitrary repository objects.

## Object versioning and immutability

When the remote backend supports versioning/object lock/immutability, zero-nvr may expose and recommend these features for disaster-recovery repositories.

Versioning/immutability state is reported in backup health where discoverable.

zero-nvr does not claim ransomware-proof backup merely because remote storage exists.

## Clean-host restore workflow

Full disaster recovery is explicit and staged.

```text
new/clean host
   ↓
install compatible zero-nvr release
   ↓
enter/load RecoveryKit
   ↓
connect backup repository
   ↓
select recovery point
   ↓
preflight compatibility checks
   ↓
restore SecretStore/keyring bootstrap
   ↓
restore PostgreSQL
   ↓
apply supported schema migration if required
   ↓
start zero-nvr in recovery/reconciliation mode
   ↓
reconcile StorageTargets/StorageObjects
   ↓
validate cameras/integrations
   ↓
resume normal services
```

Do not start normal recording workers against a half-restored database.

## Restore preflight

Before destructive/full restore, verify:

- backup manifest checksum;
- database backup integrity/status;
- required RecoveryKit/key IDs;
- backup-target accessibility;
- PostgreSQL compatibility;
- zero-nvr application/schema compatibility;
- destination storage paths;
- enough local free space;
- operator authorization/re-authentication;
- whether a running instance must enter maintenance mode.

Preflight failures stop before overwriting the current system.

## Restore version compatibility

BackupManifest stores:

```text
zero_nvr_version
database_schema_revision
postgres_version
backup_format_version
```

Restore rules:

- same supported version: restore directly;
- older supported schema into newer zero-nvr: restore then run controlled migrations;
- newer schema into older zero-nvr: reject unless an explicit compatible downgrade path exists;
- incompatible PostgreSQL major/version format: use the backup engine's supported migration/restore path rather than copying data directories blindly.

Never silently start an older application against a newer incompatible schema.

## Existing-host restore

A full restore over an existing system requires maintenance/recovery mode.

Recommended flow:

```text
create safety backup of current state where possible
stop mutating workers
stop recording control-plane mutations
restore selected backup
validate
restart services
```

Media ingest/recording behavior during full control-plane restore must be explicit in UI. The product should prefer a controlled maintenance window over pretending there is no interruption.

## Point-in-time recovery semantics

PITR restores PostgreSQL metadata to a canonical UTC point.

After PITR, physical media/archive may contain objects created after the restored database point.

Therefore zero-nvr runs storage reconciliation.

Possible outcomes:

```text
DB row + media object
  -> normal

media object newer than restored DB
  -> orphan/reconcile candidate

DB row but object missing
  -> missing/error state

remote object exists with valid detached metadata
  -> reconcile according to safe import rules
```

Never delete post-recovery "extra" media automatically merely because the restored DB does not yet reference it.

## Storage reconciliation after restore

Reconciliation uses:

- StorageObject metadata;
- object keys;
- RecordingSegment IDs;
- checksums/sizes;
- detached _camera.json metadata;
- backup manifest;
- remote/local storage scans where explicitly supported.

Unknown media first enters a quarantine/reconciliation state.

No automatic destructive cleanup occurs until ownership/identity is established.

## Remote-only playback after disaster recovery

If local recording disks are lost but remote archive survives:

```text
restore database + keyring
        ↓
reconnect archive StorageTarget
        ↓
StorageObject = remote
        ↓
PlaybackResolver
        ↓
timeline/playback available
```

Local cache may populate on demand.

Historical media does not need to be bulk-downloaded before the NVR becomes usable.

## Reusing one remote target

A single remote target may safely serve both roles when configured:

```text
archive_remote
backup
```

Use separate object prefixes, retention policies, permissions, and lifecycle rules.

Deleting expired recording media must never delete database/system backup objects, and backup retention must never purge recording archive objects.

## Backup repository credentials and least privilege

Where possible, use a dedicated backup credential/policy separate from recording archive credentials even when both use the same S3 endpoint/bucket.

Recommended separation:

```text
recording archive prefix
  read/write/delete according to media policy

backup prefix
  backup-engine permissions
  optional versioning/object-lock protection
  stricter delete policy
```

This reduces the blast radius of one credential compromise.

## Scheduling

Backup jobs use canonical scheduling/timezone rules.

Backup operations must avoid unnecessary contention with recording hot paths.

Possible controls:

- schedule heavy full backups in low-load windows;
- bandwidth/concurrency limits;
- I/O priority where available;
- separate local staging path;
- WAL archiving remains continuous when PITR is enabled.

Recording correctness has priority over non-urgent backup throughput.

## Alerting

Backup health integrates with Spec 0014.

Alert types include:

```text
backup.failed
backup.overdue
backup.verification_failed
backup.restore_test_failed
backup.target_unavailable
backup.wal_archive_lag
backup.recovery_kit_stale
backup.no_remote_media_protection
```

A backup alert never stops recording by itself.

## Permissions

Initial permissions:

```text
backup.view
backup.manage
backup.restore
backup.export
```

Semantics:

- backup.view: view policies/history/health without secrets;
- backup.manage: configure schedules/targets/retention and trigger backup/test;
- backup.restore: perform restore/PITR operations;
- backup.export: create/download encrypted portable backup or RecoveryKit.

Full restore and RecoveryKit export require recent re-authentication and MFA when enabled.

## Audit

Audit at minimum:

```text
backup.policy_created
backup.policy_updated
backup.started_manual
backup.deleted
backup.restore_test_started
backup.restore_test_completed
backup.restore_started
backup.restore_completed
backup.pitr_requested
backup.portable_export_created
backup.recovery_kit_exported
backup.recovery_kit_regenerated
```

Audit never contains recovery passphrase, repository secret, keyring plaintext, or decrypted secret payload.

## UI

System > Backup & Recovery shows:

```text
Protection Overview
  Database: Protected / Warning / Critical
  PITR window: ...
  Last verified backup: ...
  Last restore test: ...
  RecoveryKit: Current / Stale / Missing
  Media remote-protection: ...%

Backup Policies
Backup History
PITR
Restore Tests
RecoveryKit
Portable Migration Backup
```

Restore UI uses a guided wizard with preflight and explicit confirmation.

Normal configuration/support export remains distinct from disaster-recovery backup.

## Acceptance tests

1. S3 archive + backup on one target:
   - separate prefixes and retention;
   - recording purge cannot remove backups;

2. database backup:
   - base/full backup completes and verifies;
   - WAL archive advances recoverable window;

3. PITR:
   - restore to a selected UTC time;
   - expected database state appears;
   - newer media objects remain reconciliation candidates rather than being deleted;

4. lost local recording disks:
   - restored DB/keyring reconnects remote StorageObjects;
   - remote-only historical playback works without bulk download;

5. lost database host:
   - clean host + RecoveryKit can locate/decrypt required recovery material and restore;

6. missing RecoveryKit/key:
   - encrypted database secrets remain unavailable;
   - product reports explicit critical recovery problem;

7. snapshot-only rclone/OpenList target:
   - portable/system snapshots work;
   - UI does not falsely advertise PITR;

8. backup corruption:
   - verification fails;
   - backup is not marked READY/healthy;

9. automated restore test:
   - isolated restore succeeds without changing production database;

10. key rotation:
   - RecoveryKit becomes stale until regenerated;
   - old required key material is not retired prematurely;

11. retention:
   - repository dependency rules preserve required PITR chain/base backup;

12. backup target outage:
   - recording continues;
   - backup health/alerts degrade independently.

## Invariants

1. Recording archive and system/database backup are separate protection layers.
2. System backup does not duplicate all recording media by default.
3. Local-only media is never falsely reported as disaster-protected.
4. PostgreSQL PITR uses a mature database backup engine; zero-nvr does not implement WAL protocol mechanics itself.
5. Backup target capability determines whether PITR can be offered.
6. SecretStore ciphertext without matching keyring is not a complete recovery.
7. A complete disaster-recovery repository must be accessible without first restoring the lost SecretStore.
8. RecoveryKit is strongly encrypted and controlled outside PostgreSQL.
9. Backup success distinguishes upload, verification, and restore testing.
10. PITR/storage reconciliation never automatically deletes unreferenced post-recovery media.
11. Remote archive can provide playback after local-disk loss without bulk redownload.
12. Backup and recording objects use separate prefixes/lifecycle rules even on one target.
13. Full restore uses preflight and maintenance/recovery mode.
14. Restore compatibility is explicit by app/schema/PostgreSQL version.
15. Backup retention never breaks a required PITR dependency chain.
16. Backup credentials/key material never appear in normal APIs/logs/audit.
17. Backup failures never directly stop healthy recording.
18. First production release includes UI, alerts, audit, scheduled verification, and clean-host disaster recovery.
19. Non-obvious backup/PITR/recovery/reconciliation logic requires comments per Development Guidelines.
