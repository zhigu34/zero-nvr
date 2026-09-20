# Spec 0010 — Recording Storage Targets and Host-Managed Storage

Status: **accepted**

## Goal

Define the V1 recording-storage boundary without turning zero-nvr into a RAID/JBOD/filesystem manager or distributed storage scheduler.

Core rule:

> zero-nvr manages recording destinations and lifecycle policy. The operating system/NAS/storage platform owns disk aggregation, RAID, filesystem redundancy, mounts, and block-device failover.

See [Project Baseline](../PROJECT_BASELINE.md).

## Storage model

The canonical product abstraction is **StorageTarget**, not StoragePool.

Typical V1 target classes:

```text
LOCAL_RECORDING
RCLONE_ARCHIVE
PLAYBACK_CACHE
BACKUP
```

A target may expose more than one capability when the underlying path/backend safely supports it, but the product must keep recording, archive, cache, and backup lifecycle semantics distinct.

## Local recording target

Normal recording writes first to a local or host-mounted filesystem path:

```text
Camera
  -> ZLMediaKit
  -> LOCAL_RECORDING StorageTarget
```

Examples:

- ext4/xfs path;
- ZFS dataset;
- Btrfs filesystem;
- LVM-backed filesystem;
- mergerfs mount;
- hardware/software RAID filesystem;
- administrator-managed NAS mount that has been explicitly accepted for hot recording.

zero-nvr sees the resulting mounted path. It does not create or manage the underlying pool.

## What zero-nvr must not implement

V1 does not implement:

- RAID creation/rebuild;
- JBOD aggregation;
- disk spanning;
- block-device discovery as a storage manager;
- filesystem creation;
- ZFS/Btrfs/LVM pool administration;
- a sticky-balanced multi-disk placement scheduler;
- per-segment disk balancing;
- distributed storage reservations;
- automatic cloud storage as hot-recording failover.

If an administrator wants several disks to behave as one recording volume, use a mature host/storage solution and present the resulting path to zero-nvr.

## Target selection

There is one system default local recording target.

A RecordingPolicy/Camera may optionally select another explicitly configured LOCAL_RECORDING target.

This is configuration, not automatic load balancing.

Conceptually:

```text
RecordingPolicy
  storage_target_id   # nullable -> system default
```

A target change should take effect at a safe recording boundary where practical.

## StorageTarget product state

Useful fields/derived status:

```text
id
name
kind
enabled
config/reference
total_bytes
used_bytes
free_bytes
health_state
last_health_at
last_error
created_at
updated_at
```

Suggested health projection:

```text
UNKNOWN
OK
PRESSURE
CRITICAL
OFFLINE
READ_ONLY
```

High-frequency filesystem telemetry does not need to be persisted continuously; meaningful state changes should become SystemEvents/Audit records where appropriate.

## Disk pressure

Each local recording target has configurable watermarks.

Initial product defaults may begin around:

```text
warning  = 80%
high     = 85%
critical = 95%
```

These values are configuration defaults, not hard-coded business constants.

Under pressure:

1. evaluate normal retention eligibility;
2. never silently delete protected recordings;
3. if archive-before-delete is required, do not delete the local copy until a verified remote RecordingLocation exists;
4. if no legal deletion can restore space, raise a critical condition;
5. do not silently violate explicit protection or hard-retention guarantees.

## Local target failure

If the active recording filesystem becomes unavailable/read-only/full:

- ZLM/adapter reports the recording failure;
- zero-nvr marks the capability degraded/critical;
- current partial/finalized media is reconciled where possible;
- new recording is not redirected to an archive remote;
- V1 does not invent an automatic multi-disk failover scheduler.

The administrator may repair the host storage or select another LOCAL_RECORDING target.

If later evidence shows that a simple ordered local-target failover materially improves reliability without recreating a storage manager, it requires a separate ADR before becoming baseline behavior.

## Remote archive boundary

Remote archive is asynchronous:

```text
local RecordingLocation AVAILABLE
-> worker invokes rclone copy/copyto
-> verify
-> remote RecordingLocation AVAILABLE
-> retention may later remove local copy
```

S3/WebDAV/SFTP/SMB/OneDrive/OpenList-backed remotes are archive/restore destinations, not normal hot recording destinations.

Archive outage must not stop healthy local recording.

## Playback cache

Remote-only playback uses a bounded local playback-cache target:

```text
remote RecordingLocation
-> rclone restore/copyto
-> PLAYBACK_CACHE
-> ZLMediaKit VOD
```

The cache is disposable and excluded from normal system backup.

## Multiple local paths

Multiple LOCAL_RECORDING targets may exist for explicit routing or migration.

Example:

```text
Camera group A -> /recordings-a
Camera group B -> /recordings-b
```

zero-nvr does not automatically balance them.

A history may therefore contain RecordingLocations on different targets after an administrator changes policy or migrates data. PlaybackResolver hides that physical detail.

## Target removal

A StorageTarget with unique retained media cannot simply disappear from product state.

Before removal:

- stop selecting it for new writes;
- determine whether unique RecordingLocations remain;
- require migration, explicit deletion, or acknowledgement according to policy;
- preserve enough state to explain temporarily missing/offline media;
- audit destructive actions.

Unplugging a disk does not mean the database should forget that its media existed.

## Host storage guidance

Documentation should recommend mature host-level choices rather than reproducing them:

- single disk/filesystem for simplest deployments;
- ZFS/Btrfs/RAID for redundancy;
- mergerfs for simple multi-disk aggregation where appropriate;
- NAS/shared filesystem when its latency/reliability is suitable;
- SMART monitoring via host/smartmontools when hardware visibility is available.

zero-nvr may surface basic filesystem capacity and optional SMART summaries, but it is not the storage-platform control plane.

## Acceptance tests

1. One local target:
   - ZLM records directly to the configured path;
   - actual free/used capacity is visible.

2. Disk pressure:
   - retention runs according to policy;
   - protected media is never silently deleted.

3. Archive-required deletion:
   - local copy remains until remote verification succeeds.

4. Local target becomes read-only/offline:
   - recording/storage health becomes critical;
   - no direct fallback to rclone/OpenList cloud recording occurs.

5. Administrator changes a camera/policy to another local target:
   - new media is written to the new target at a safe boundary;
   - older media remains playable through its existing RecordingLocation.

6. Remote archive outage:
   - local recording continues;
   - archive task remains retryable/degraded.

7. Target removal with unique media:
   - destructive removal is blocked or explicitly acknowledged/migrated.

8. Remote-only playback:
   - restore to bounded playback cache works without requiring FUSE.

## Invariants

1. StorageTarget is the product abstraction; V1 has no zero-nvr-managed StoragePool.
2. Host/storage software owns RAID/JBOD/filesystem aggregation and failover.
3. Normal recording writes to a LOCAL_RECORDING target first.
4. Remote archive never becomes implicit hot-recording failover.
5. Remote archive failure does not stop healthy local recording.
6. Protected media is never silently deleted.
7. Archive-before-delete policy is enforced against verified RecordingLocation state.
8. Playback remains independent of which physical target holds a valid copy.
9. Missing/offline targets remain explainable rather than being silently forgotten.
10. Any future automatic multi-target placement/failover requires an ADR and demonstrated need.
