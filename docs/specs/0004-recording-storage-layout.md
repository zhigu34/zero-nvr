# Spec 0004 — Recording Storage Layout and Time Index

Status: **accepted**

## Goal

Define the canonical storage layout, file naming, cross-day behavior, staging rules, and database indexing for formal recordings.

This specification applies to canonical RecordingSegments. Idle tmpfs PrebufferFragments remain temporary media and follow Spec 0003.

## Core principle

> PostgreSQL owns the recording timeline. File paths organize storage; they are never the source of truth.

Playback, retention, upload, export, event linking, and recovery must use RecordingSegment / StorageObject metadata rather than infer business state from directory names or filenames.

## Time model

All authoritative recording timestamps are stored in UTC.

Canonical fields include:

```text
RecordingSession.started_at
RecordingSession.ended_at
RecordingSegment.started_at
RecordingSegment.ended_at
DetectionEvent.started_at
DetectionEvent.ended_at
```

UI/API presentation may convert UTC timestamps to the configured/user timezone.

Filesystem partitioning also uses the UTC `RecordingSegment.started_at` date. This avoids DST ambiguity and prevents storage layout from changing with UI timezone settings.

## Formal segment cadence

The configured formal segment duration defines the normal RecordingSegment clock.

Default:

```text
formal_record_segment_seconds = 300
```

For a healthy RecordingSession starting at `S`, normal boundaries are:

```text
S
S + 300s
S + 600s
S + 900s
...
```

A calendar/day boundary does not alter this cadence.

Example:

```text
segment:
2026-09-18 23:58:30Z
      ↓
2026-09-19 00:03:30Z
```

This remains one 5-minute RecordingSegment.

zero-nvr must not force a split at midnight merely to fit a date directory.

## Canonical object-key layout

Use stable camera identity and UTC start date:

```text
recordings/
  {camera_id}/
    {YYYY}/
      {MM}/
        {DD}/
          {start_utc}_{segment_id}.mp4
```

Example:

```text
recordings/
  0199...camera-id/
    2026/
      09/
        18/
          20260918T235830.000Z_0199...segment-id.mp4
```

Rules:

- use immutable `camera_id`, never camera display name, in canonical paths;
- date partition is derived from segment `started_at` in UTC;
- use filesystem-safe compact UTC timestamp formatting;
- include immutable `segment_id` to guarantee uniqueness;
- do not place RecordingSession id, event type, camera name, or recording mode in the canonical path;
- do not encode mutable business metadata into filenames.

The same relative object key should be reusable across LocalStorage/S3/rclone/OpenList where supported.

## Cross-day segments

If a RecordingSegment crosses midnight, it remains stored under the date on which it started.

Example:

```text
started_at = 2026-09-18T23:58:30Z
ended_at   = 2026-09-19T00:03:30Z

path:
recordings/{camera_id}/2026/09/18/20260918T235830.000Z_{segment_id}.mp4
```

The next normal segment begins at 00:03:30Z and is stored in the September 19 directory.

Directory date therefore means:

> the UTC date on which the segment started

not:

> the only calendar date contained by the media.

## Why there is no session directory

Do not use:

```text
recordings/{camera_id}/{recording_session_id}/...
```

as the canonical layout.

Reasons:

- continuous sessions may last a very long time;
- events may annotate an existing continuous/manual/schedule timeline;
- storage retention and playback are time-oriented;
- StorageObject may move between backends without changing business identity;
- the database already represents RecordingSession ↔ RecordingSegment relationships.

Session membership belongs in metadata, not path hierarchy.

## Writing and finalize path

Incomplete media must never appear at its final canonical object key.

Local staging layout:

```text
{recording_root}/.staging/{camera_id}/{segment_id}.partial
```

Conceptual lifecycle:

```text
ALLOCATED
   ↓
WRITING (.partial)
   ↓
FINALIZING
   ↓
verify media / size / timestamps
   ↓
rename/move to canonical final path
   ↓
READY
```

Within one filesystem, final publication should use an atomic rename where practical.

If staging and final storage are different filesystems/backends:

```text
write/copy temporary object
      ↓
verify
      ↓
publish final key
      ↓
mark StorageObject READY
      ↓
remove staging source
```

A database row must not report a final object as ready until the final publication/verification step succeeds.

## Prebuffer layout

Idle PrebufferFragments are not stored under canonical `recordings/`.

Recommended tmpfs layout:

```text
/run/zero-nvr/prebuffer/
  {camera_id}/
    {fragment_id}.mp4
```

or an equivalent configurable tmpfs root.

Prebuffer filenames are implementation details. The fragment table/index records their actual timestamps.

When required by an event, fragment ranges are consumed into the first formal RecordingSegment according to Spec 0003. After the finalized formal segment is verified and no other protection requires the fragments, the temporary files become GC-eligible.

## RecordingSegment identity

`RecordingSegment.id` is the stable logical identity of a canonical formal segment.

Recommended properties:

- globally unique;
- sortable/time-friendly identifiers are preferred (for example UUIDv7), but database correctness must not depend on lexical file ordering;
- the ID remains unchanged when the media is uploaded/moved to another StorageBackend.

A RecordingSegment can therefore have multiple StorageObjects while keeping one business identity.

## Database timeline index

Historical playback must query overlapping RecordingSegments by timestamp, not scan directories.

Conceptual query condition:

```text
camera_id = :camera_id
AND started_at < :query_end
AND ended_at > :query_start
AND integrity_status is playable
```

Recommended database index:

```text
(camera_id, started_at)
```

and, as query volume requires, an additional overlap/range-oriented index strategy may be introduced.

The first V2 implementation should favor simple deterministic B-tree indexes before adding specialized indexing.

## RecordingSegment metadata

RecordingSegment must carry enough metadata to explain and recover the stored media:

```text
id
camera_id
stream_role
sequence
started_at
ended_at
duration
codec
container
size
integrity_status
completion_reason
created_at
```

Physical location remains represented by StorageObject:

```text
StorageObject
  logical_kind = recording_segment
  logical_id   = RecordingSegment.id
  storage_target_id
  object_key
  size
  checksum
  state
  verified_at
```

RecordingSegment therefore does not become invalid when its local file is later moved or deleted after verified remote upload.

## Sequence semantics

`sequence` orders segments within one RecordingSession.

Normal example:

```text
session S
sequence 0  12:00:07 ─ 12:05:07
sequence 1  12:05:07 ─ 12:10:07
sequence 2  12:10:07 ─ 12:12:30
```

Sequence is useful for diagnostics and deterministic ordering but is not the authoritative time axis. Absolute timestamps remain authoritative.

If an abnormal interruption creates a new RecordingSession/recovery generation, sequence may restart for that new session.

## Recovery / reconciliation

On startup or after media-service failure, zero-nvr reconciles:

- database RecordingSegments / StorageObjects;
- staging `*.partial` files;
- finalized local media objects.

Rules:

1. an indexed READY object missing from storage is marked unhealthy/missing; it is not silently forgotten;
2. a finalized media file with no matching database metadata is quarantined/reconciled, not immediately deleted;
3. stale `*.partial` files are inspected and either recovered or cleaned according to age/state;
4. recovered abnormal segments use an explicit `completion_reason`;
5. recovery never rebuilds authoritative timestamps solely from filename parsing when media/database evidence is available.

## Retention and deletion

Retention decisions operate on database metadata.

Never implement:

```text
delete directory because its YYYY/MM/DD name is older than N days
```

as the sole retention rule.

Instead:

```text
RecordingSegment / StorageObject policy eligibility
      ↓
reference / upload / verification checks
      ↓
delete physical object
      ↓
record state transition
```

Empty date directories may be cleaned after their objects are removed.

## Cross-day playback

PlaybackResolver ignores directory boundaries.

Example query:

```text
23:55:00Z ───────── 00:10:00Z
```

may resolve:

```text
.../2026/09/18/segment-A.mp4
.../2026/09/18/segment-B.mp4   # crosses midnight
.../2026/09/19/segment-C.mp4
.../2026/09/19/segment-D.mp4
```

The browser receives one logical timeline.

## Invariants

1. PostgreSQL timestamps/relations are authoritative; filenames/directories are not.
2. Canonical timestamps are UTC; UI timezone conversion is presentation only.
3. Formal recording cadence is not reset by midnight or directory boundaries.
4. A segment crossing midnight remains one RecordingSegment and is stored under its UTC start date.
5. Normal healthy intermediate segments follow configured duration; only real session/recovery boundaries may produce partial segments.
6. Canonical paths use immutable camera/segment identities, never mutable camera names.
7. Incomplete media uses staging/temp names and is not published as a READY final object.
8. PrebufferFragments live outside canonical recording storage and remain temporary.
9. RecordingSegment identity survives movement across storage backends.
10. Historical playback uses timestamp queries, not directory scanning.
11. Retention/deletion uses metadata state and reference checks, not date-folder age alone.
12. Cross-day playback is one logical timeline independent from filesystem partitioning.
13. Recovery must make partial/missing/orphan media observable rather than silently discarding it.
14. Non-obvious storage/recovery/path behavior requires comments per Development Guidelines.
