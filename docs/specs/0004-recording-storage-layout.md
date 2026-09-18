# Spec 0004 — Recording Storage Layout and Time Index

Status: **accepted**

## Goal

Define the canonical storage layout, file naming, cross-day behavior, staging rules, and database indexing for formal recordings.

This specification applies to canonical RecordingSegments. Idle tmpfs PrebufferFragments remain temporary media and follow Spec 0003.

## Core principle

> PostgreSQL owns the authoritative recording timeline, while the local filesystem must remain independently human-browsable.

Playback, retention, upload, export, event linking, and recovery use RecordingSegment / StorageObject metadata. However, a user who mounts the recording disk without zero-nvr must still be able to locate media by camera, date, hour, and start/end time from the directory and filename alone.

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

Filesystem presentation uses a configured `recording_timezone` (default: system recording timezone) so recordings remain intuitive when browsed outside zero-nvr. Filenames include the numeric UTC offset and an immutable short segment ID to avoid ambiguity around DST/repeated local times.

The database remains UTC. Changing `recording_timezone` affects only future path generation and must not retroactively rename existing media unless an explicit migration is requested.

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

## Human-readable canonical local layout

Local recording storage must be understandable without the database.

Each Camera has a stable `storage_label` used for the recording directory. It defaults to the camera display name when the Camera is created, is sanitized for portable filesystem use, and is paired with a short immutable camera-id suffix.

Example camera directory:

```text
客厅__a1b2c3d4
```

The suffix prevents collisions when two cameras have the same name.

Recommended local layout:

```text
recordings/
  {storage_label}__{camera_short_id}/
    {YYYY-MM-DD}/
      {HH}/
        {local_start_with_offset}__{local_end_with_offset}__{segment_short_id}.mp4
```

Example:

```text
recordings/
  客厅__a1b2c3d4/
    2026-09-19/
      01/
        2026-09-19_01-42-07+0800__01-47-07+0800__e91f2a6c.mp4
```

For a segment that ends on another date, the end portion includes the end date as well:

```text
2026-09-19_23-58-30+0800__2026-09-20_00-03-30+0800__e91f2a6c.mp4
```

Rules:

- preserve a human-readable camera `storage_label`; do not expose a bare UUID directory as the normal local layout;
- append a short immutable Camera ID suffix to guarantee uniqueness;
- partition by local start date/hour in the configured `recording_timezone`;
- include human-readable local start and end timestamps in the filename;
- include the UTC offset in timestamps;
- include a short immutable segment-id suffix to guarantee uniqueness;
- avoid mutable event type/session state in the filename;
- use characters safe across Linux, SMB/NAS, Windows-mounted disks, and common object-storage tools;
- the full Camera/RecordingSegment UUID remains in the database and optional metadata, not necessarily in the visible filename.

### storage_label stability

`storage_label` is a storage identity, distinct from the mutable Camera display name.

Recommended behavior:

1. when a Camera is created, initialize `storage_label` from the display name;
2. allow the user to customize it before recordings exist;
3. once canonical media exists, changing the Camera display name does not rename historical directories;
4. changing `storage_label` after media exists requires an explicit storage migration operation rather than silently splitting one camera across folders.

This keeps paths human-readable while preserving stable references.

### Object-storage key strategy

Remote/object backends may use the same human-readable relative key when the backend handles UTF-8 paths safely.

If a backend requires stricter keys, StorageBackend may map the local human-readable path to a backend-safe object key while preserving the original local filename and RecordingSegment metadata.

The local disk layout is optimized for independent human access; backend object-key compatibility must not force local media into UUID-only directories.

## Cross-day segments

A RecordingSegment is never force-split merely because the configured local calendar date changes.

Example in `Asia/Shanghai`:

```text
started_at = 2026-09-19 23:58:30+08:00
ended_at   = 2026-09-20 00:03:30+08:00

path:
recordings/客厅__a1b2c3d4/2026-09-19/23/
  2026-09-19_23-58-30+0800__2026-09-20_00-03-30+0800__e91f2a6c.mp4
```

The file stays under the local date/hour on which it started. The filename itself shows that it crosses into the next day.

The next normal segment is stored under the date/hour of its own start.

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
{recording_root}/.staging/{camera_short_id}/{segment_id}.partial
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

## Detached-disk usability

A recording disk should remain useful even when zero-nvr, PostgreSQL, and the original server are unavailable.

Minimum requirements:

- directories identify the camera in human-readable form;
- date/hour folders are understandable without conversion tools;
- filenames contain start and end times;
- every MP4 is directly playable as a standalone finalized file;
- unique short IDs prevent collisions.

Additionally, zero-nvr should maintain a lightweight camera metadata file:

```text
recordings/{storage_label}__{camera_short_id}/_camera.json
```

Suggested contents:

```text
camera_id
storage_label
last_known_display_name
recording_timezone
created_at
```

This file is convenience metadata only and is not authoritative over PostgreSQL.

A per-day human-readable index (for example `_index.csv` or `_index.json`) may be generated later, but V2 correctness must not depend on it.

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
.../客厅__a1b2c3d4/2026-09-18/23/...mp4
.../客厅__a1b2c3d4/2026-09-18/23/...mp4   # crosses midnight
.../客厅__a1b2c3d4/2026-09-19/00/...mp4
.../客厅__a1b2c3d4/2026-09-19/00/...mp4
```

The browser receives one logical timeline.

## Invariants

1. PostgreSQL timestamps/relations are authoritative; filenames/directories are not.
2. Canonical database timestamps are UTC; human-facing local paths use configured recording_timezone and include numeric UTC offsets.
3. Formal recording cadence is not reset by midnight or directory boundaries.
4. A segment crossing local midnight remains one RecordingSegment and is stored under its local start date/hour.
5. Normal healthy intermediate segments follow configured duration; only real session/recovery boundaries may produce partial segments.
6. Local canonical paths combine a stable human-readable Camera storage_label with immutable short Camera/segment IDs; bare UUID-only local paths are not the default user-facing layout.
7. Incomplete media uses staging/temp names and is not published as a READY final object.
8. PrebufferFragments live outside canonical recording storage and remain temporary.
9. RecordingSegment identity survives movement across storage backends.
10. Historical playback uses timestamp queries, not directory scanning.
11. Retention/deletion uses metadata state and reference checks, not date-folder age alone.
12. Cross-day playback is one logical timeline independent from filesystem partitioning.
13. A detached recording disk remains browseable by camera/date/hour/start-end time without PostgreSQL.
14. Camera folders include convenience _camera.json metadata for detached identification.
15. Recovery must make partial/missing/orphan media observable rather than silently discarding it.
16. Non-obvious storage/recovery/path behavior requires comments per Development Guidelines.
