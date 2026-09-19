# Spec 0005 — Recording Retention, Disk Pressure, and Safe Purge

Status: **accepted**

## Goal

Define how zero-nvr keeps recordings for the configured period, protects important media, preserves enough free disk space for continued recording, and safely removes local copies after verified remote upload.

This specification applies to canonical RecordingSegments / StorageObjects. Idle PrebufferFragments follow the short-lived GC rules from Spec 0003.

## Core principles

1. Retention is metadata-driven; never delete recordings by directory age alone.
2. Expiration policy and emergency disk-pressure cleanup are separate mechanisms.
3. Active/writing media is never a purge candidate.
4. A verified remote copy makes a local copy cheaper to evict, but upload success alone is insufficient; verification is required.
5. User-locked media is never automatically deleted.
6. Event/manual media receives higher retention priority than ordinary continuous/schedule media.
7. Disk-pressure deletion is observable: every early purge records why it happened.

## RetentionPolicy

Retention is configurable and may be system-default or camera-specific.

Initial V2 defaults:

```text
continuous_keep_days = 7
schedule_keep_days   = 7
event_keep_days      = 30
manual_keep_days     = 30
```

These are product defaults, not hard-coded constants.

A camera may inherit the system RetentionPolicy or override individual values.

A policy of `0` means that class has no age-based guarantee after the recording is finalized, subject to safety/reference rules.

"Forever" is not represented by an enormous day count. Long-term/indefinite preservation uses an explicit lock/hold.

## Why retention is claim-based

One physical RecordingSegment may satisfy more than one business purpose.

Example:

```text
continuous RecordingSession
12:00 ───────────────────────── 12:05

motion event
             12:02:10 ─ 12:02:45
```

The same 5-minute RecordingSegment is ordinary continuous footage **and** contains an event that may need 30-day retention.

Therefore a segment must not be assigned only one destructive retention class.

zero-nvr uses retention claims/holds conceptually:

```text
RetentionClaim
  id
  recording_segment_id
  reason
  priority
  retain_until
  source_type
  source_id
  created_at
```

Typical reasons:

```text
continuous_policy
schedule_policy
event_policy
manual_policy
user_lock
upload_source
export_job
system_recovery
```

Effective segment retention is the strongest active claim.

For finite claims:

```text
effective_retain_until = max(active retain_until values)
```

An indefinite `user_lock` has no automatic expiry.

When an event overlaps an already-recording continuous/schedule segment, zero-nvr adds an event retention claim to the affected RecordingSegment(s); it does not duplicate the media merely to obtain longer retention.

## Retention priority

Initial priority order from easiest to sacrifice to hardest:

```text
0  temporary/staging/derived disposable artifacts
1  continuous / schedule
2  event
3  manual
4  user_locked
```

Priority is used only for cleanup ordering. It does not change the authoritative timeline.

User lock always wins and is never automatically purged.

## Normal expiration cleanup

The normal retention worker deletes only media whose required retention has expired.

A local StorageObject is normally purgeable only when all of the following are true:

```text
state == READY
AND segment is not WRITING/FINALIZING
AND no active playback/export/upload operation requires the local file
AND no active/indefinite retention claim protects it
AND effective_retain_until <= now
AND deletion will not violate last-valid-copy rules
```

Before physical unlink/delete, the worker re-checks eligibility transactionally/conditionally to avoid races with a new event claim, user lock, upload, export, or playback request.

## Last-valid-copy rule

Retention applies to the recording, not merely one filesystem object.

If no verified remote copy exists, the local object is normally the last valid copy.

zero-nvr must not delete the last valid copy before the recording's effective retention expires.

If a verified remote copy exists:

```text
local copy
  ↓
may become local-purge eligible
  ↓
RecordingSegment remains available through remote StorageObject
```

Metadata is retained while at least one valid media copy remains and while product history/retention rules require it.

## Remote upload and local purge

Upload lifecycle:

```text
LOCAL_READY
   ↓
UPLOADING
   ↓
VERIFYING
   ↓
REMOTE_READY
   ↓
LOCAL_PURGE_ELIGIBLE
```

Rules:

- an upload command returning success is not sufficient;
- remote object size/checksum/integrity must be verified according to backend capability;
- only `REMOTE_READY` counts as a valid redundant copy;
- failed/incomplete upload keeps the local source protected when it is the last valid copy;
- local purge never deletes the database RecordingSegment itself when a verified remote StorageObject still exists.

Under disk pressure, a local copy that already has a verified remote copy is preferred for deletion before an equivalent local-only recording.

## Disk capacity guard

Disk protection uses configurable watermarks.

Initial defaults:

```text
warning_usage_percent       = 80
cleanup_start_percent       = 85
critical_usage_percent      = 92
emergency_usage_percent     = 96
cleanup_target_percent      = 80
min_free_bytes              = configurable (deployment/storage specific)
```

The guard considers both percentage and absolute free bytes. A storage target enters pressure mode if either configured free-space constraint is violated.

### NORMAL

```text
usage < 80%
```

- normal age-based retention cleanup;
- no unexpired recording is deleted.

### WARNING

```text
usage >= 80%
```

- surface health warning;
- run cleanup/reconciliation promptly;
- still delete only normally eligible/expired objects.

### PRESSURE

```text
usage >= 85%
```

- aggressively remove expired media;
- clean disposable derived/staging artifacts;
- purge verified-remote local copies that are already normally local-purge eligible;
- continue until usage is near `cleanup_target_percent` where possible.

### CRITICAL

```text
usage >= 92%
```

After all normally eligible media is exhausted, zero-nvr may perform **early local eviction** to protect recording continuity.

Order:

1. verified-remote local copies, oldest first;
2. oldest unexpired priority-1 continuous/schedule local-only recordings;
3. only then higher-priority unlocked media if the system reaches emergency pressure.

Every early eviction emits EventLog/health/audit data containing:

```text
storage_target_id
recording_segment_id
previous_retain_until
priority
reason = disk_pressure
usage_before
usage_after
remote_copy_available
```

### EMERGENCY

```text
usage >= 96%
or free space below hard reserve
```

Goal: avoid filesystem exhaustion and recorder corruption.

Deletion ordering remains:

```text
verified-remote copies
    ↓
continuous/schedule
    ↓
event
    ↓
manual
```

Always oldest first within the same class unless another claim requires otherwise.

Never automatically delete:

- the currently WRITING/FINALIZING segment;
- media required by an active transaction/assembly;
- user-locked media.

If no eligible object remains, zero-nvr must surface a critical `storage_exhausted` state rather than silently deleting user-locked media.

Recording may then fail/stop because the storage target is exhausted; that failure must be explicit and recoverable.

## Why event media is not absolutely undeletable

Event footage is higher priority than normal continuous footage, but treating every event as permanent can eventually make a finite disk unusable.

Therefore:

- events receive longer default retention;
- events are evicted after continuous/schedule media under severe pressure;
- users can explicitly lock recordings/events that must never be auto-deleted.

This keeps automatic operation sustainable while giving the user an explicit permanent-protection mechanism.

## User lock / unlock

The UI/API must support locking a RecordingSession/event or selected recording range.

Lock behavior:

- create indefinite retention claim(s) for all affected RecordingSegments;
- display locked state clearly;
- locked media is excluded from automatic retention and disk-pressure purge;
- unlocking removes only the user-lock claim; other claims remain.

A lock does not prevent an administrator from explicitly deleting media through a deliberate destructive operation with normal authorization/audit rules.

## Shared segments and event claims

Because a 5-minute formal RecordingSegment may contain several events, event retention attaches to the physical segment(s) needed for those events.

Example:

```text
segment S1: 12:00 ─ 12:05
event E1:          12:02:10 ─ 12:02:30
event retention: 30 days
continuous retention: 7 days
```

Result:

```text
S1 effective retention = 30 days
```

No media duplication is required.

If future storage optimization introduces precise sub-segment extraction for long-term event archives, that is a derived optimization and must not change the correctness of this baseline.

## Deletion transaction

Safe conceptual local deletion flow:

```text
select candidate
   ↓
acquire conditional/transactional delete ownership
   ↓
re-check:
  state
  claims
  active references
  remote-copy state
   ↓
mark DELETING
   ↓
delete physical object
   ↓
confirm absence
   ↓
mark DELETED / update RecordingSegment availability
   ↓
clean empty date directory if applicable
```

If physical deletion fails, do not mark the StorageObject deleted.

The operation is idempotent and retryable.

## Recording directory cleanup

The human-readable directory layout from Spec 0004 remains intact while files exist.

After all recording files for a date are deleted:

```text
recordings/{name_id}/{YYYY-MM-DD}/
```

may be removed if empty.

The Camera directory and `_camera.json` may remain even when no recordings currently exist, because they are useful for detached-disk identity.

## Metadata retention after media purge

Deleting media does not necessarily mean immediately deleting all business metadata.

At minimum zero-nvr may retain lightweight history sufficient to show:

- that a RecordingSession/Event existed;
- recording/event timestamps;
- why media is unavailable;
- when/why the media was purged.

The UI should distinguish:

```text
media available
media remote-only
media expired/purged
media missing/error
```

Metadata-history duration can be configured separately from media retention later.

## Configuration surface

Storage/Retention settings should expose at least:

```text
continuous_keep_days
schedule_keep_days
event_keep_days
manual_keep_days

warning_usage_percent
cleanup_start_percent
critical_usage_percent
emergency_usage_percent
cleanup_target_percent
min_free_bytes
```

Camera-level retention overrides belong with Camera Recording/Retention settings.

User lock is per recording/event/range and is not a global day-count setting.

## Invariants

1. Normal retention and emergency disk-pressure cleanup are separate.
2. Retention is claim-based so one physical segment can satisfy multiple business purposes safely.
3. Effective finite retention is the maximum of active claims.
4. User lock creates indefinite automatic-retention protection.
5. Active/writing/finalizing media is never automatically purged.
6. Event media has higher purge priority than continuous/schedule media; manual is higher again.
7. A verified remote copy is preferred for local eviction before deleting local-only media.
8. Upload success without verification never makes the local source safely purgeable.
9. The last valid copy is not deleted before effective retention expires during normal cleanup.
10. Under critical disk pressure, unlocked unexpired media may be evicted by priority to preserve recording continuity.
11. User-locked media is never automatically deleted even under emergency pressure.
12. Every early disk-pressure purge is explicitly logged and observable.
13. Deletion re-checks state/claims immediately before physical removal.
14. Retention cleanup is idempotent and retryable.
15. Directory age/name alone never authorizes deletion.
16. Media purge and metadata-history deletion are separate concerns.
17. Non-obvious retention/race/pressure behavior requires comments per Development Guidelines.

## Storage-pool pressure reference

Retention watermarks apply per StorageTarget. Placement may move future segments away from a pressured target at a safe boundary, while critical write failure may trigger target failover. Remote archive targets are not direct recording-hot fallbacks. See [Spec 0010 — Recording Storage Pool, Target Selection, and Failover](0010-recording-storage-pool-and-failover.md).
