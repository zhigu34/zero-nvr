# Spec 0010 — Recording Storage Pool, Target Selection, and Failover

Status: **accepted**

## Goal

Define how zero-nvr chooses where new recording media is written when multiple storage targets exist, how it behaves when a disk/path becomes unhealthy or full, and how remote/archive storage participates without making live recording depend on cloud/network availability.

Core rule:

> Recording hot-path storage and archive/remote storage are different responsibilities.

## Storage roles

StorageTarget has an explicit role/capability.

Initial V2 roles:

```text
recording_hot
archive_remote
playback_cache
```

### recording_hot

Used for direct formal RecordingSegment writes.

Initial V2 supported forms:

- local filesystem;
- locally mounted block/filesystem storage;
- administrator-managed mounted NAS/filesystem only when it behaves like a reliable local filesystem and passes health checks.

A recording-hot target must support staging/partial writes, durable finalize, free-space reporting, safe publish semantics from Spec 0004, and predictable write latency.

### archive_remote

Used asynchronously after a local RecordingSegment is finalized.

Examples:

- S3;
- rclone-backed remote;
- OpenList-backed remote.

Remote archive availability must not determine whether the camera can keep recording locally.

### playback_cache

Temporary/local cache for remote-only playback. It is not a canonical recording destination.

## StoragePool

Multiple recording-hot targets are grouped into a StoragePool.

Conceptual model:

```text
StoragePool
  id
  name
  enabled
  selection_policy
  failover_enabled
  min_stable_seconds
  created_at
  updated_at
```

Pool membership:

```text
StoragePoolTarget
  storage_pool_id
  storage_target_id
  priority
  weight
  enabled
```

A camera/RecordingPolicy references:

```text
recording_storage_pool_id
```

If absent, the system default recording pool is used.

## StorageTarget additions

Conceptual recording-related fields:

```text
StorageTarget
  id
  type
  name
  role
  enabled
  priority
  config
  quota

  health_state
  write_state
  total_bytes
  used_bytes
  free_bytes
  last_health_at
  last_successful_write_at
  last_error

  created_at
  updated_at
```

Initial health states:

```text
unknown
healthy
degraded
pressure
critical
offline
read_only
```

Initial write states:

```text
eligible
draining
ineligible
```

A target can remain readable for playback while being ineligible for new recording writes.

## Default target-selection policy

Initial V2 default:

```text
selection_policy = sticky_balanced
```

Behavior:

1. choose among healthy/eligible recording-hot targets;
2. exclude targets below hard free-space reserve or in critical/offline/read-only state;
3. prefer the target with the best usable free-space/capacity score;
4. use configured priority/weight as tie-break/control;
5. once selected for an active RecordingSession, keep that target sticky while healthy.

The exact scoring formula is implementation tuning. Correctness must not depend on one exact percentage formula.

Why sticky:

- avoids moving every 5-minute segment between disks;
- makes detached-disk browsing easier;
- reduces mount/cache churn;
- avoids oscillation when two disks have nearly equal free space.

## Selection scope

The active write target is associated with the active RecordingSession/runtime, not permanently baked into Camera identity.

Conceptually:

```text
RecordingSession
  active_storage_target_id
```

This field is runtime/current-placement metadata and may change after a real storage failover.

RecordingSegment / StorageObject still record the actual physical target for every finalized file.

## Starting a recording

When RecordingManager needs to enter FORMAL_RECORDING:

```text
RecordingIntent set becomes non-empty
        ↓
StoragePlacementManager.select_target(pool)
        ↓
healthy target found?
   ├─ yes -> allocate staging path -> start formal media
   └─ no  -> storage_unavailable / recording failure state
```

Target selection happens before the first persistent write.

For event recording that uses tmpfs prebuffer, protected prebuffer material remains safe until the chosen persistent target is ready, within the limits defined by Spec 0003.

## Normal recording behavior

While the active target remains healthy and above pressure constraints:

- keep writing normal 5-minute segments to that target;
- do not rebalance merely because another target becomes slightly emptier;
- retention/cleanup operates independently on each StorageTarget;
- remote upload proceeds asynchronously after segment finalize.

## Soft pressure behavior

A target entering normal pressure state does not necessarily interrupt the current segment.

Preferred behavior:

```text
current segment
   -> finish safely if possible

next segment boundary
   -> StoragePlacementManager may choose another eligible target
```

This is a planned placement change, not a media/source failure.

If the active target can safely continue and cleanup is expected to restore headroom, the system may remain sticky.

The decision must include hysteresis so targets do not alternate every segment.

## Hard/critical storage failure

Examples:

- filesystem becomes read-only;
- mount disappears;
- ENOSPC / hard reserve breached;
- sustained write failure;
- I/O errors;
- target health becomes offline/critical.

Then:

1. stop writing to the failed target;
2. finalize/recover the current partial segment if possible;
3. mark the interrupted segment/object state explicitly;
4. choose another eligible target from the same StoragePool;
5. start a new physical RecordingSegment on the replacement target;
6. keep RecordingIntent and RecordingSession alive if recording is still required.

Conceptually:

```text
RecordingSession
------------------------------------------------

disk A
[ segment 1 ][ partial/interrupted ]

disk B
                         [ segment 2 ][ segment 3 ]
```

Storage failover may create a real media gap while the recorder switches. That gap must be visible.

## Completion reason

A segment interrupted by the storage destination uses:

```text
completion_reason = storage_failure
```

If a planned safe target switch occurs exactly at a normal segment boundary:

```text
completion_reason = normal_boundary
```

Do not label a planned safe rebalance as failure.

## Physical segment clock after failover

### Planned boundary switch

If target placement changes at an existing normal segment boundary:

```text
segment cadence is unchanged
```

Example:

```text
12:00-12:05 disk A
12:05-12:10 disk B
```

### Unplanned storage failure mid-segment

If disk A fails at 12:03:17 and media resumes on disk B at 12:03:20:

```text
A: 12:00:00 - 12:03:17  storage_failure
gap: 3s
B: 12:03:20 - 12:08:20
```

A real storage discontinuity resets the physical 5-minute segment clock from actual recovered write time, consistent with Spec 0008.

## Recovery of a failed target

When a failed target becomes healthy again:

```text
offline/critical
      ↓
probing
      ↓
healthy-but-stabilizing
      ↓
eligible
```

Do not immediately preempt the currently healthy active write target.

Initial rule:

- recovered target must remain healthy for at least configurable min_stable_seconds;
- then it becomes eligible for future placement;
- current active recording stays on its present target until a safe boundary/session transition unless pressure/failure requires change.

This prevents storage flapping.

## Target draining / maintenance

An administrator may mark a recording-hot target:

```text
write_state = draining
```

Meaning:

- do not place new RecordingSessions on it;
- existing current segment/session may finish or migrate at a safe segment boundary according to policy;
- existing recordings remain readable;
- retention/upload/migration jobs may continue.

After no active writer remains:

```text
write_state = ineligible
```

This supports disk replacement without abruptly killing every recorder.

## Remote archive is not hot failover

S3/rclone/OpenList do not become direct live recording destinations merely because all local disks are full/offline.

If no recording-hot target is available:

```text
recording state = storage_unavailable
```

and the system raises critical health/alerts.

Why:

- remote latency can be unpredictable;
- temporary network loss would directly break recording;
- many remote APIs do not provide filesystem-like atomic finalize semantics;
- hot-path correctness should not depend on cloud credentials or Internet availability.

Future versions may add a dedicated remote-streaming recorder backend, but that is outside initial V2.

## Archive upload policy

After local RecordingSegment reaches READY:

```text
local READY
   ↓
UploadJob
   ↓
REMOTE_READY verified
```

Only then can Spec 0005 decide whether the local StorageObject may be purged.

Remote targets may be assigned different upload policies, for example:

```text
all recordings
event/manual only
selected cameras
scheduled archive window
```

Exact policy UI can evolve independently from hot target placement.

## Per-camera storage routing

A camera may use the system default StoragePool or an explicit recording_storage_pool_id.

Use cases:

- high-bitrate cameras on a larger pool;
- critical cameras on dedicated disks;
- temporary cameras on a smaller pool.

The normal UI should expose Storage Pool selection rather than raw path complexity.

## Capacity accounting

Placement uses usable capacity rather than raw filesystem size.

Conceptually:

```text
usable_free =
  min(
    filesystem_free,
    quota_remaining
  )
  - hard_reserve
```

Targets below hard reserve are ineligible for new writes.

Soft/critical/emergency watermarks from Spec 0005 still apply per target.

Pool-level health summarizes whether at least one target can accept recording.

## StoragePool health

Conceptual states:

```text
healthy
degraded
critical
unavailable
```

Examples:

- healthy: normal eligible targets;
- degraded: one target unavailable but recording can continue;
- critical: only one marginal target remains;
- unavailable: no eligible recording-hot target.

Pool health should surface in system/dashboard status.

## Concurrency and allocation

Target selection/allocation must be serialized or transactionally protected enough that many cameras starting at once do not all make stale free-space decisions.

Required properties:

- allocate target/path atomically enough for correctness;
- refresh capacity after reservations/starts;
- no two target-selection workers create conflicting object paths;
- target health change can invalidate a pending allocation before recorder start;
- retries are idempotent.

A lightweight reservation may track expected near-term write budget, but V2 does not need a complex distributed storage scheduler.

## Storage reservations

For multi-camera starts/recovery storms, optional conceptual reservation:

```text
StorageWriteReservation
  id
  storage_target_id
  camera_id
  recording_session_id
  estimated_bytes
  expires_at
  state
```

This prevents many cameras from selecting the same target based on one stale free-space sample.

Single-host V2 may begin with per-target locking and add persisted reservations if real load requires it.

## Detached-disk behavior

Spec 0004 human-readable paths remain target-local.

Each recording-hot target may contain:

```text
recordings/
  客厅_a1b2c3d4/
  门口_e5f6a7b8/
```

A camera's history may span multiple physical disks after balancing/failover.

PostgreSQL / StorageObject metadata provides unified playback.

Detached browsing still works per disk because each target preserves the same human-readable layout and _camera.json identity metadata.

## Playback

PlaybackResolver ignores which hot disk originally held the segment.

```text
RecordingSegment
   ↓
StorageObjects
   ├─ local disk A
   ├─ local disk B
   └─ remote archive
```

Resolver selects a valid available copy according to locality/health.

Storage failover never creates a separate user-facing timeline.

## Deleting/removing a StorageTarget

A target with retained unique media must not be silently removed from configuration.

Before destructive removal:

- enumerate READY objects that have no other verified copy;
- block removal or require an explicit migration/delete decision;
- stop/drain active writers;
- record audit state.

Unplugged/missing disks remain represented as offline StorageTargets so their missing media can be explained rather than forgotten.

## UI behavior

Storage page should show:

```text
Storage Pool: Default Recordings
  Health: Healthy

  Disk A
    Role: Recording
    State: Healthy
    Used / Free
    Active writers

  Disk B
    Role: Recording
    State: Healthy
    Used / Free
    Active writers

Remote Archive
  S3
    State: Healthy
    Upload queue
```

Camera Recording Settings should normally expose:

```text
Recording storage pool:
  Default Recordings
```

Advanced view may show current target and recent failover history.

## EventLog / audit

Important events:

```text
storage_target_degraded
storage_target_recovered
storage_target_offline
storage_pool_degraded
storage_pool_unavailable
recording_target_selected
recording_target_switched
recording_target_failover
storage_write_failed
storage_target_draining
```

Failover records should include camera_id, recording_session_id, old_target_id, new_target_id, failed_segment_id, reason, gap_started_at, and recovered_at.

## Acceptance tests

1. two healthy local targets:
   - new sessions distribute according to sticky_balanced policy;
   - one active session remains sticky while target is healthy;

2. target reaches soft pressure:
   - current segment remains safe;
   - optional switch happens only at safe boundary;
   - no per-segment oscillation;

3. target disappears mid-segment:
   - current object becomes interrupted/recoverable;
   - alternate target is selected;
   - new physical segment starts;
   - same RecordingSession/Intent survives;

4. target recovers:
   - it passes stability period;
   - current healthy writer is not immediately preempted;

5. no eligible local target:
   - storage_pool = unavailable;
   - recording reports storage_unavailable;
   - system does not silently start direct recording to S3/rclone/OpenList;

6. remote archive outage:
   - local recording continues;
   - UploadJobs retry independently;

7. planned drain:
   - no new sessions are placed;
   - active writer moves/stops only at safe boundary according to policy;

8. playback across disks:
   - one historical timeline spans disk A, disk B, and remote archive;

9. target removal with unique media:
   - removal is blocked or requires explicit migration/delete decision.

## Invariants

1. Direct formal recording uses an eligible recording-hot target, not an archive-remote target.
2. Remote archive failure must not stop healthy local recording.
3. A RecordingSession has one active hot write target at a time.
4. Active target remains sticky while healthy to avoid placement flapping.
5. Planned target switching occurs at safe segment boundaries where possible.
6. Mid-segment storage failure may split physical media but does not end RecordingSession while RecordingIntent remains active.
7. Real storage discontinuity resets physical segment cadence from actual recovered write time.
8. Recovered targets pass a stability period and do not immediately preempt healthy active writers.
9. A target below hard free-space reserve is ineligible for new writes.
10. StorageTarget and StoragePool health are observable.
11. Human-readable target-local paths remain compatible with Spec 0004.
12. PlaybackResolver unifies segments regardless of original disk/backend.
13. StorageTarget removal never silently forgets unique retained media.
14. Placement/failover is idempotent and concurrency-safe enough to avoid duplicate writers/paths.
15. Non-obvious storage placement/failover behavior requires comments per Development Guidelines.

## Authorization reference

Storage health viewing and StorageTarget/StoragePool mutation use separate permissions. Even an authorized storage administrator cannot bypass unique-media safety invariants when draining/removing a target. See [Spec 0011 — Authentication, Camera-Scoped Authorization, and Audit](0011-auth-authorization-and-audit.md).
