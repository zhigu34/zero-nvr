# Spec 0005 — Recording Retention, Disk Pressure, and Safe Purge

Status: **accepted**

## Goal

Define how zero-nvr deletes recording copies safely while respecting retention, explicit protection, archive requirements, and disk pressure.

Core rule:

> Retention decides whether a RecordingLocation copy may be deleted. It never silently destroys protected evidence or assumes an archive is safe before verification.

See [Project Baseline](../PROJECT_BASELINE.md), [Spec 0004](0004-recording-storage-layout.md), and [Spec 0010](0010-recording-storage-pool-and-failover.md).

## RetentionPolicy

Conceptual fields:

~~~text
id
name
scope_type                    global | camera_group | camera
scope_id                      nullable
ordinary_keep_days
event_keep_days
manual_keep_days
mode                          best_effort | hard
require_archive_before_delete
enabled
created_at
updated_at
~~~

More specific enabled policy may override the global default.

The exact precedence rule must be deterministic and visible in the UI.

## Recording reasons

RecordingSegment may retain compact historical reason flags:

~~~text
continuous
schedule
event
manual
~~~

Retention uses those durable facts plus overlapping Events/RecordingTriggers.

A segment containing both ordinary continuous video and an Event may inherit the longer event retention without creating a second media copy.

V1 does not require a RetentionClaim table merely to duplicate this derivable state.

## RecordingProtection

Explicit user/system protection is range-based:

~~~text
camera_id
started_at
ended_at
reason
created_by
expires_at
~~~

If a RecordingSegment overlaps an active protection range, its canonical copies are protected from automatic retention deletion.

Protection is metadata. Do not copy the media into a second locked directory merely to protect it.

## Normal age retention

For a segment/location, compute the required retention horizon from:

- policy scope;
- segment recording reasons;
- overlapping Event/RecordingTrigger facts;
- explicit RecordingProtection;
- target/copy role where policy distinguishes local vs archive;
- archive-before-delete requirement.

A local location becomes an ordinary purge candidate only when:

~~~text
location.state == AVAILABLE
AND segment is finalized
AND no active RecordingProtection overlaps
AND required retention has expired
AND no active playback/export operation requires that local file
AND archive-before-delete condition is satisfied
~~~

Eligibility must be rechecked immediately before deletion to avoid races.

## Archive-before-delete

When configured, local RecordingLocation AVAILABLE plus a configured remote target is not sufficient.

Required:

~~~text
at least one required remote RecordingLocation == AVAILABLE
AND backend verification succeeded
~~~

Then local deletion may become eligible.

A remote location in ARCHIVING, FAILED, or MISSING never satisfies archive-before-delete.

## Copy / verify / delete

Archive path:

~~~text
local AVAILABLE
-> remote ARCHIVING
-> rclone copy/copyto
-> verify
-> remote AVAILABLE
-> retention may delete local
~~~

Do not make rclone move the normal product archive workflow.

Do not use whole-tree rclone sync semantics when local retention deletion could unintentionally mirror-delete archive content.

## Physical deletion

Deletion lifecycle:

~~~text
AVAILABLE
-> DELETING
-> physical delete
-> DELETED
~~~

If physical delete fails:

- do not claim DELETED;
- retain an explainable failure/error state;
- retry only through the background-task policy;
- never delete the RecordingSegment merely to hide the inconsistency.

A deleted local location may coexist with an AVAILABLE remote location.

## Last-valid-copy safety

Before deleting any copy, determine whether policy permits losing it.

If it is the only AVAILABLE canonical copy and required retention has not expired, deletion is forbidden.

Even after normal age retention expires, an active RecordingProtection still forbids automatic deletion.

## Disk pressure

Disk pressure is evaluated per local recording target using real filesystem free/used capacity.

Initial configurable guidance:

~~~text
warning  ~ 80%
high     ~ 85%
critical ~ 95%
~~~

These are defaults/guidance, not hard-coded constants.

### Warning

- surface UI/system health;
- normal retention continues.

### High

- immediately evaluate eligible expired recordings;
- prioritize local copies that already have verified remote copies;
- schedule cleanup until configured recovery headroom is restored.

### Critical

- continue deleting only copies that policy legally permits;
- emit critical Alert/SystemEvent;
- if no legal candidate exists, do not silently break hard retention or RecordingProtection.

The product may have to stop/risk new recording rather than destroy explicitly protected evidence.

## BEST_EFFORT vs HARD

BEST_EFFORT is a target retention duration. Under severe disk pressure, old ordinary unprotected footage may be deleted earlier if policy explicitly allows it. The UI/audit trail must make early deletion explainable.

HARD is a minimum retention guarantee. The cleanup engine may not violate it automatically.

If disk pressure cannot be recovered without violating a HARD policy or protection:

~~~text
storage health = CRITICAL
recording risk = explicit
alert = raised
~~~

Do not silently downgrade HARD to BEST_EFFORT.

## Cleanup priority

When several legal candidates exist, prefer:

1. disposable cache/derived artifacts, handled by their own cache cleanup;
2. expired local recording copies that already have verified remote copies;
3. expired ordinary unprotected local-only copies;
4. event/manual copies only when their required retention has expired.

Never treat current/writing media as a normal purge candidate.

## Remote retention

Remote RecordingLocations can have their own retention lifecycle.

Remote deletion is also performed through the storage adapter/rclone and transitions the target RecordingLocation through DELETING/DELETED.

Deleting local and remote copies should never be coupled through filesystem sync semantics.

## Segment metadata after copy deletion

RecordingSegment is separate from its locations.

When one location is deleted:

- segment timestamps/history do not change;
- another AVAILABLE location may remain playable.

When every canonical location is deleted/missing, the product may retain segment/tombstone metadata long enough to explain the historical gap according to metadata-retention policy.

Metadata cleanup is a separate concern from physical-media deletion.

## Audit / explainability

Important destructive actions record:

- camera/segment/location;
- storage target;
- policy/reason;
- archive verification state;
- actor for manual deletion;
- time/result/error.

A user should be able to distinguish normal expiry, BEST_EFFORT early deletion, manual deletion, copy deletion, and unexpected missing media.

## Acceptance tests

1. Normal retention deletes expired unprotected copies safely.
2. Event-containing segment uses longer event retention without duplicate media.
3. RecordingProtection blocks automatic deletion.
4. ARCHIVING/FAILED remote copy does not permit archive-required local deletion; verified AVAILABLE remote can.
5. rclone failure keeps the still-required local source.
6. High disk pressure prefers eligible local copies with verified remote copies.
7. HARD policy refuses illegal early deletion and raises critical health.
8. BEST_EFFORT early deletion is policy-controlled and explainable.
9. Physical delete failure is not falsely marked DELETED.
10. A required last valid copy is not silently removed.

## Invariants

1. Retention deletes copies/RecordingLocations, not abstract segment time.
2. RecordingProtection cannot be silently overridden by disk pressure.
3. Archive success means verified remote RecordingLocation AVAILABLE.
4. Failed/pending archive never permits archive-required local deletion.
5. rclone move/sync is not the default archive lifecycle.
6. Physical-delete failure never becomes false DELETED state.
7. Hard retention is actually hard.
8. Remote archive failure never stops healthy local recording.
9. Every destructive deletion is explainable.
