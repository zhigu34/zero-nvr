# Spec 0003 — Rolling MP4 Pre-buffer and Event Segment Composition

Status: **accepted**

## Goal

Define how zero-nvr provides reliable event pre-recording by using ZLMediaKit rolling MP4 recording, a tmpfs-backed short-term buffer, and logical composition of physical MP4 segments.

This design intentionally separates:

- physical MP4 segment boundaries;
- logical RecordingSession boundaries;
- event timestamps/markers.

A recording remains correct even when an event begins or ends immediately before or after a ZLM segment rollover.

## Core principle

> Physical segment boundaries are an implementation detail. RecordingSession time is the business truth.

zero-nvr must not require a physical MP4 file to start or stop exactly at an event boundary.

Example:

```text
physical segments:

S1: 12:00:00 ───────────── 12:00:20
S2: 12:00:20 ───────────── 12:00:40

event:
                    T=12:00:19
                    ↓

logical recording:
             12:00:09 ───────────────── ...
```

The logical recording may use only the required range from S1 and continue into S2. A segment rollover at 12:00:20 does not interrupt or invalidate the event recording.

## Rolling MP4 pre-buffer

For cameras that require event pre-recording, ZLMediaKit continuously produces short rolling MP4 segments.

Initial V2 defaults:

```text
idle_prebuffer_segment_seconds = 20 seconds
formal_record_segment_seconds  = 300 seconds (5 minutes)
pre_roll_seconds               = 10 seconds
post_roll_seconds              = 10 seconds
```

These are defaults, not hard-coded constants. They must be persisted as recording settings/policy and exposed in the Recording Settings UI.

The 20-second target applies only to idle tmpfs pre-buffer recording. Once a formal RecordingSession is active (continuous/manual/schedule/event), the normal persistent recording segment target defaults to 5 minutes.

The segment duration is a target, not an authoritative timeline value. zero-nvr always uses the actual timestamps/duration reported or derived for the finalized media.

The temporary recording root is backed by a bounded tmpfs mount where practical:

```text
ZLMediaKit
    ↓
rolling MP4
    ↓
tmpfs pre-buffer
    ↓
on_record_mp4
    ↓
segment index / retention worker
```

tmpfs reduces unnecessary persistent-disk writes for media that is never promoted into a retained recording.

## One recording pipeline with idle and formal modes

The tmpfs pre-buffer is an **idle mode of the same recording pipeline**, not a second recorder.

For each camera, the recording runtime has two media-writing modes:

```text
IDLE_PREBUFFER
  segment target = idle_prebuffer_segment_seconds (default 20s)
  destination    = bounded tmpfs
  retention      = ephemeral unless protected

FORMAL_RECORDING
  segment target = formal_record_segment_seconds (default 300s)
  destination    = persistent recording storage
  retention      = RecordingSession-owned
```

zero-nvr must never run both modes in parallel for the same camera merely to maintain pre-roll.

### Transition: idle pre-buffer → formal recording

When an event/manual/schedule/continuous recording request arrives while a pre-buffer segment is already being written, **do not stop or restart the recorder**.

The current pre-buffer segment is adopted by the new RecordingSession:

1. protect the current WRITING segment and required previous segment(s);
2. create/reuse the RecordingSession;
3. keep writing the current physical segment until its normal boundary;
4. when that segment finalizes, promote it from tmpfs to persistent storage if it overlaps the logical RecordingSession;
5. if the RecordingSession is still active after that boundary, the next physical segment is written directly in FORMAL_RECORDING mode using the formal segment target (default 5 minutes).

Conceptually:

```text
IDLE_PREBUFFER                         FORMAL_RECORDING
20s tmpfs segment                      5min persistent segments

──── previous ────|──── current ─────|═══════════════════════════>
                         ↑ event T
                         │
                         └─ current segment is adopted;
                            no stop/start at T
```

The first formal RecordingSession segment may therefore be shorter than the configured 5-minute target because it began life as an idle pre-buffer segment. This is expected.

If the event/manual request completes before the adopted 20-second segment reaches its natural boundary, the session may be satisfied entirely by that adopted segment; zero-nvr does not create a 5-minute segment merely because formal mode was requested briefly.

### Transition: formal recording → idle pre-buffer

When the final formal RecordingSession ends:

1. finalize the current formal physical segment at the required session end boundary when needed; the 5-minute value is a maximum/target segment duration, not a minimum duration;
2. complete/persist its RecordingSegment metadata;
3. immediately continue the same camera stream in IDLE_PREBUFFER mode with the configured idle segment target;
4. retain/reuse at least the final `pre_roll` interval of the just-finished persistent recording while the new tmpfs buffer warms.

Example:

```text
formal recording ends at 12:00:00
idle prebuffer resumes immediately

new event at 12:00:06
required pre-roll starts at 11:59:56

11:59:56 .. 12:00:00 → previous persistent recording tail
12:00:00 .. 12:00:06 → new tmpfs pre-buffer
```

This prevents a pre-roll blind period without maintaining duplicate recording paths during formal recording.

The final persistent recording tail must remain referenceable for at least the configured `pre_roll` interval after formal recording completion.

## Recording settings and runtime changes

The following recording parameters are user-configurable:

```text
prebuffer_enabled
idle_prebuffer_segment_seconds   # default 20
formal_record_segment_seconds    # default 300
pre_roll_seconds                 # default 10
post_roll_seconds                # default 10
```

The UI must present these under Recording Settings. Backend services must read them from the authoritative RecordingPolicy/RecordingSettings model instead of embedding magic numbers in code.

Configuration changes must not create avoidable media gaps:

- changing `idle_prebuffer_segment_seconds` applies to the next pre-buffer segment/cycle;
- changing `formal_record_segment_seconds` applies from the next formal physical segment and must not force-cut the current MP4 merely to apply the setting; a RecordingSession ending may still finalize a shorter last segment;
- changing pre/post-roll affects subsequent event-window calculations according to the persisted policy;
- if the camera is currently in formal recording, an idle-prebuffer setting change is stored and applied when idle pre-buffering resumes;
- invalid or unsafe values must be rejected by API validation rather than silently coerced.

The UI may show recommended defaults, but defaults and user overrides are domain configuration, not frontend-only state.

## on_record_mp4 ownership boundary

`on_record_mp4` is the primary finalize signal for a physical ZLM MP4 segment.

Before finalize, a segment is conceptually:

```text
WRITING
```

After the hook confirms the finished MP4 and zero-nvr has indexed its real timing/path metadata:

```text
READY
```

Filesystem appearance alone must not be treated as sufficient proof that a segment is complete and safe for normal processing.

## Segment retention state

Physical media state and retention/protection state are separate concepts.

Example media state:

```text
WRITING
READY
PROMOTING
PERSISTED
FAILED
```

Example retention state:

```text
EPHEMERAL
PROTECTED
PINNED
```

Meaning:

- `EPHEMERAL`: normal rolling pre-buffer media; GC may remove it when eligible;
- `PROTECTED`: temporarily protected from GC while an event/session decision is being resolved;
- `PINNED`: confirmed to belong to a retained RecordingSession.

## Event arrival at time T

When an event requiring recording arrives at timestamp `T`, the first operation is protection, not recorder restart.

Fast-path protection:

```text
1. persist the event timestamp T;
2. protect the current WRITING segment;
3. protect the immediately previous finalized segment;
4. prevent GC from deleting either while the event window is resolved.
```

Conceptually:

```text
S[n-1]                 S[n]
READY                   WRITING
  │                       │
  └── PROTECTED      PROTECTED ──┘
                            ↑
                            T
```

This fast path protects against races between event ingestion and pre-buffer cleanup.

The worker then validates the actual required media interval:

```text
required_start = T - pre_roll
```

and protects/pins every segment whose actual timeline overlaps the required interval.

The implementation must not assume that "current + previous" is always sufficient. Stream reconnects, unusual segment timing, missing files, or other discontinuities require time-based validation.

## No race with segment rollover

If `T` arrives near a natural 20-second rollover, it is acceptable for ZLM to finalize the current segment and begin another segment before zero-nvr finishes event handling.

Correctness is time-based, not filename/current-handle based.

Example:

```text
19.000s  event START @ T
20.xxx   S[n] finalizes
20.xxx   S[n+1] begins
later    event worker resolves protection
```

The worker queries/indexes segments by their actual media time and protects every segment overlapping the required window.

Therefore event recording does not depend on winning a race against ZLM's segment rollover.

## Recording boundary behavior

Normal event START must not call `stopRecord → startRecord` merely to force a file boundary. The currently written idle pre-buffer segment is adopted directly by the RecordingSession and continues to its natural boundary.

At the final event END + post-roll, zero-nvr may finalize the current formal recording segment early in order to complete the RecordingSession and immediately return to idle pre-buffer mode. The configured 5-minute formal segment duration is a target/maximum chunk size for an ongoing formal recording, not a requirement to keep recording until the full five minutes elapse.

The preferred behavior is:

```text
event START
   ↓
adopt current pre-buffer segment
   ↓
natural boundary
   ↓
continue with 5min formal segments while session remains active
   ↓
final event END + post-roll
   ↓
finalize current formal segment if needed
   ↓
resume 20s idle pre-buffer
```

No parallel recorder is created during this transition.

## RecordingSession logical boundaries

RecordingSession stores the desired business interval independent from physical segment boundaries.

Example fields/semantics:

```text
logical_started_at
logical_ended_at
actual_media_started_at
actual_media_ended_at
```

For an event session:

```text
logical_started_at = first_required_event_time - pre_roll

logical_ended_at =
    final stateful event END + post_roll
    or
    final instant event time + post_roll
```

Physical media may begin before `logical_started_at` and end after `logical_ended_at`.

That extra media is acceptable and must not change the event timeline presented to the user.

## RecordingSessionSegment

A RecordingSession may span one or many physical RecordingSegments.

Use an explicit association that records which part of each physical segment belongs to the logical recording.

Conceptual model:

```text
RecordingSessionSegment
  recording_session_id
  recording_segment_id
  sequence
  use_started_at
  use_ended_at
  created_at
```

Example:

```text
S1 physical: 12:00:00 ───────── 12:00:20
S2 physical: 12:00:20 ───────── 12:00:40
S3 physical: 12:00:40 ───────── 12:01:00

logical recording:
             12:00:09 ───────────────── 12:00:45

links:

S1 → use 12:00:09 .. 12:00:20
S2 → use 12:00:20 .. 12:00:40
S3 → use 12:00:40 .. 12:00:45
```

The physical MP4 files may remain unchanged.

This allows:

- event recording across arbitrary segment boundaries;
- one logical playback timeline;
- no mandatory transcode in the recording hot path;
- future reuse/annotation of already-existing media;
- precise business timestamps even when media files contain additional footage.

## Event continuation and post-roll

While any stateful event remains ACTIVE, new finalized segments that overlap the active RecordingSession are automatically protected/pinned.

After the final event ends:

```text
planned_end_at = final_event_end + post_roll
```

For an instant event:

```text
planned_end_at = event_time + post_roll
```

If another event arrives before the pending end:

- keep the same RecordingSession;
- protect/pin the newly required media;
- extend/recalculate the logical end according to Spec 0002;
- do not restart ZLM recording.

After the logical end has passed, retain enough subsequent media to cover the logical end, wait for any required WRITING segment to finalize, then complete the session links.

## Playback

Normal playback should not require generation of a merged MP4 file.

PlaybackResolver can present multiple RecordingSegments as one logical timeline using:

- RecordingSession logical start/end;
- ordered RecordingSessionSegment links;
- per-link use-start/use-end times.

The player should seek to the logical recording start and event Marker timestamps, not blindly to the first byte/time of the first physical MP4.

## Single-file export / download

When a single standalone MP4 is requested, an asynchronous export/consolidation job may crop and concatenate the needed ranges.

Preferred strategy:

1. identify ordered RecordingSessionSegment inputs;
2. calculate the required sub-range from the first and last segment;
3. concatenate compatible media without re-encoding when safe;
4. if an exact arbitrary boundary cannot be produced safely with stream copy, either:
   - retain a small surrounding GOP and preserve zero-transcode behavior; or
   - re-encode only where an exact export boundary is explicitly required;
5. verify the output before publishing it.

Do not make synchronous event ingestion or RecordingSession finalization wait for an export merge.

Original retained segments remain authoritative until the derived export is verified and normal retention policy allows deletion.

## GC and concurrency

The GC worker must not be globally paused because one camera has an event.

Deletion eligibility is per segment.

Conceptually:

```text
can_delete =
    media_state == READY
    AND retention_state == EPHEMERAL
    AND expired
    AND not referenced by a retained session
```

Protection and deletion must be concurrency-safe.

Before unlinking a file, GC must revalidate that the segment is still deletable. An event arriving at the same time as cleanup must be able to prevent deletion before unlink.

Implementation may use transactional/conditional database updates, row locking, or another mechanism that provides equivalent protection.

The concurrency rule and race rationale must be documented in code according to Development Guidelines.

## tmpfs capacity protection

tmpfs must be bounded.

With the 20-second physical segment target, the normal idle pre-buffer retention target is approximately:

```text
previous finalized segment + current writing segment
≈ 20s .. 40s of compressed media per camera
```

The business pre-roll guarantee remains 10 seconds. Retaining roughly 40 seconds gives boundary and normal scheduling margin without intentionally keeping the earlier 90-second cache target.

Late events whose authoritative occurrence time is older than available buffered/persisted coverage are still recorded, but pre-roll degradation must be logged explicitly.

Capacity policy should support at least:

```text
tmpfs_max_bytes
per_camera_buffer_budget
buffer_retention_target
```

When pressure occurs:

1. delete oldest eligible EPHEMERAL segments first;
2. never silently delete PROTECTED/PINNED media;
3. surface structured EventLog/health state when pre-roll coverage becomes degraded;
4. expose enough diagnostics to explain a missing/partial pre-roll.

## Promotion to persistent storage

Pinned segments that must survive tmpfs eviction are promoted to the configured persistent storage target.

Because tmpfs and the recording volume may be different filesystems, promotion must not assume an atomic cross-filesystem rename.

Safe conceptual flow:

```text
source segment
   ↓
copy to destination *.partial
   ↓
verify size / integrity as configured
   ↓
flush/finalize
   ↓
atomic rename inside destination filesystem
   ↓
mark persistent
   ↓
release tmpfs source when safe
```

Incomplete `*.partial` files must be recoverable/cleanable after restart.

## Invariants

1. A segment rollover never loses an event recording as long as the required physical media still exists in the pre-buffer.
2. Event START/END do not require exact physical MP4 boundaries.
3. The default idle pre-buffer rolling MP4 target is 20 seconds; the default formal-recording physical segment target is 300 seconds (5 minutes); actual segment timestamps are authoritative.
4. Event pre-roll/post-roll remain 10 seconds by default and are independent from either physical segment duration.
5. Event arrival immediately protects current/previous media and then resolves the complete required interval by actual timestamps.
6. Normal event handling does not stop/restart ZLM to force MP4 boundaries.
7. RecordingSession logical time is authoritative for product behavior.
8. RecordingSessionSegment maps logical recordings onto physical MP4 ranges.
9. Physical files may contain extra media before/after a logical session.
10. Playback may span multiple physical files without creating a merged archive.
11. Single-file merge/crop is a derived export operation, not part of the recording hot path.
12. GC must re-check retention state immediately before deletion.
13. tmpfs pressure must degrade observably, never by silently deleting protected media.
14. Idle tmpfs pre-buffering and formal recording are two modes of one recording pipeline; they must not run as duplicate parallel recorders for the same camera.
15. A formal recording request adopts the currently written idle pre-buffer segment without stop/start; after its natural boundary, subsequent segments use the formal recording target/destination while the session remains active.
16. The first segment of a formal RecordingSession may therefore be a promoted idle-prebuffer segment shorter than the formal segment target.
17. The configured formal segment duration is a target/maximum for ongoing recording, not a minimum; the final segment may be finalized early when the RecordingSession ends.
18. After formal recording ends, idle prebuffering resumes immediately and may reuse the final persistent recording tail to cover the warm-up interval.
19. Pre-buffer segment duration, formal recording segment duration, pre-roll, and post-roll are persisted user-configurable recording settings; code must not hard-code them.
20. Segment-duration setting changes take effect at a safe next-boundary transition and must not force-cut the currently written MP4 merely to apply configuration.
21. Non-obvious state, timing, race, and media-boundary logic requires complete comments per Development Guidelines.
