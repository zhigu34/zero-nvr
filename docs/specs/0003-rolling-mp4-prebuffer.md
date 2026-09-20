# Spec 0003 — EVENT_ONLY Pre-roll Candidate

Status: **design candidate — POC-03/04 required before freeze**

## Goal

Provide reliable EVENT_ONLY pre-roll/post-roll without:

- a custom H.264/H.265 packet ring buffer;
- a second camera pull;
- duplicate event recorders;
- mandatory RecordingSession/PrebufferFragment tables;
- synchronous FFmpeg assembly in the recording hot path.

Accepted product semantics:

- default pre-roll target: about 10 seconds;
- default post-roll target: about 10 seconds;
- overlapping Events remain independent Event/RecordingTrigger rows;
- overlapping triggers extend one effective retention/promotion window;
- one camera has one normal ZLM recording pipeline;
- missing pre-roll is reported honestly rather than fabricated.

The physical mechanism remains POC-gated.

## Current ZLM source audit

Three mature ZLM-native approaches were reviewed.

### A — startRecordTask

Current ZLM exposes:

~~~text
/index/api/startRecordTask
  back_ms
  forward_ms
  path
~~~

and can write historical GOP-ring content plus a fixed amount of future video.

However the current implementation creates a new independent MP4Muxer/RingReader for every call.

Consequences:

- there is no task ID;
- there is no public extend-current-task operation;
- repeated calls are separate recording tasks/files rather than one naturally extended recorder;
- the direct MP4Muxer path does not use the normal MP4Recorder on_record_mp4 finalization/broadcast path;
- forward duration must be known when the task starts.

This is useful for fixed event clips but is not the preferred canonical mechanism for stateful/unknown-duration EVENT_ONLY recording.

Current upstream issues have also reported historical-length/repeated-call edge cases. Therefore startRecordTask remains a comparison/fallback candidate rather than the V1 baseline.

### B — ordinary startRecord + GOP Ring

The normal ZLM recorder is created through makeRecorder(), which flushes an existing frame GOP Ring into the new recorder before continuing with live frames.

This is attractive because it keeps:

- normal MP4Recorder;
- on_record_mp4;
- normal segmentation;
- one recorder.

But the current frame Ring is not simply created by setting rtp_proxy.gop_cache; a supported API action must first cause getFrameReader()/equivalent Ring creation.

The current hook start_time also reflects MP4Recorder file creation wall time and is not designed as an authoritative absolute timestamp for historical frames flushed before that moment.

Therefore this candidate must not be selected until both Ring lifecycle and canonical wall-clock timing are proven.

### C — rolling ZLM recorder to bounded tmpfs, promote whole finalized fragments

This is the current **primary POC candidate**.

~~~text
Camera
  ↓
ZLMediaKit
  ↓
one normal MP4/fMP4 recorder
  ↓
short finalized fragments in bounded tmpfs
  ↓ on_record_mp4
ephemeral fragment index/state
  ↓ Event window overlap
copy/verify/promote selected fragments
  ↓
persistent RecordingSegment + RecordingLocation
~~~

The recorder never changes merely because an Event begins/ends.

Events control **promotion/retention**, not recorder lifecycle.

This uses ZLM's mature normal recorder and hook path continuously while keeping long-term EVENT_ONLY storage small.

## Why candidate C is simpler

When no Event is active:

- ZLM records short fragments into bounded tmpfs;
- oldest finalized ephemeral files are deleted after the buffer window expires;
- nothing is inserted as canonical retained RecordingSegment merely because it existed temporarily.

When Event A arrives at T:

~~~text
required_start = T - pre_roll
effective_end  = T + post_roll   # for an instant Event
~~~

zero-nvr protects/promotes all finalized fragments overlapping required_start..effective_end.

If the currently open fragment overlaps the window, it is handled when its normal on_record_mp4 hook arrives.

When Event B overlaps:

~~~text
effective_end = max(current_effective_end, event_B_required_end)
~~~

No recorder restart occurs.

Event A and Event B remain separate Events/RecordingTriggers.

After the final effective_end is covered by finalized promoted fragments, the camera simply continues normal rolling tmpfs recording.

## Ephemeral state

V1 does **not** require a PrebufferFragment business table.

Ephemeral fragment state may be held by:

- recent on_record_mp4 hook metadata in memory;
- a bounded per-camera in-memory deque;
- direct scan/reconciliation of the known tmpfs recording root after control-plane restart.

Required fragment facts:

~~~text
camera_id
file_path
actual start_at
actual end_at
duration
size
finalized
protected/promoting state
~~~

These are implementation/runtime facts until the file is promoted.

When promoted, create normal canonical:

~~~text
RecordingSegment
RecordingLocation
~~~

using the fragment's actual media time.

## Fragment duration

Initial POC should test a short target such as:

~~~text
5s
10s
20s
~~~

The target is not hard-coded product truth.

Trade-off:

- shorter fragments reduce extra retained media and promotion latency;
- longer fragments reduce filesystem/hook churn;
- ZLM cuts MP4 on keyframe boundaries, so actual duration depends on GOP.

The POC must measure actual durations with at least two GOP intervals.

A likely V1 default should be chosen from measured CPU/file-count/memory and coverage behavior rather than from aesthetics.

## Buffer retention

The tmpfs buffer must be explicitly bounded.

For requested pre-roll P and maximum expected Event delivery delay L, keep enough finalized + current media to cover at least:

~~~text
buffer_window >= P + L + fragment_boundary_margin
~~~

The POC should start with a conservative window such as 30–40 seconds and measure real memory usage.

Capacity is based on compressed bitrate:

~~~text
bytes_per_camera ≈ bitrate_bits_per_second / 8 * buffer_seconds
~~~

Example only:

~~~text
4 Mbit/s * 40s ≈ 20 MB per camera
16 cameras ≈ 320 MB
~~~

The product must expose the resulting memory budget instead of silently allocating unbounded tmpfs.

## Promotion

Promotion is a local copy from ephemeral tmpfs to the selected LOCAL recording StorageTarget.

Safe flow:

~~~text
tmpfs finalized fragment
  ↓
destination *.partial
  ↓ copy
verify size/basic media validity as configured
  ↓
atomic rename inside destination filesystem
  ↓
create canonical RecordingSegment + RecordingLocation AVAILABLE
  ↓
ephemeral source can later be deleted
~~~

Do not assume cross-filesystem rename is atomic.

Promotion is asynchronous through Huey in production, but protection against tmpfs GC must happen immediately when a matching Event/Trigger arrives.

## Whole-fragment retention

V1 does not need exact frame-level trimming during promotion.

If the required Event interval begins/ends inside a fragment, retain the whole overlapping fragment.

Therefore physical retained coverage may include additional media before pre-roll or after post-roll.

The Event marker and requested range remain exact product timestamps.

Exact user export can later trim/remux/transcode via FFmpeg.

This avoids FFmpeg work in the recording hot path.

## Canonical segment strategy

Each promoted finalized tmpfs fragment may become one canonical RecordingSegment.

V1 does not require concatenating short EVENT_ONLY fragments into synthetic 5-minute RecordingSegments.

Timeline query merges adjacent coverage, so users do not see file fragmentation as separate playback sessions.

A later compaction job is optional only if real file-count measurements prove it necessary.

## Crash behavior

Candidate C depends on POC-02:

- normal finalized tmpfs fragments are already valid;
- current hidden in-progress fragment should use the selected MP4/fMP4 format;
- after ZLM process crash, recover surviving media where possible;
- host reboot/power loss clears tmpfs, so only already-promoted persistent fragments are durable.

The product must describe EVENT_ONLY tmpfs as a short pre-buffer, not as durable storage before promotion.

## Control-plane restart

The ZLM recorder should continue even if FastAPI/worker restarts.

After recovery:

1. scan known tmpfs recording paths;
2. combine discovered finalized files with current active RecordingTriggers;
3. protect/promote any file overlapping a still-required window;
4. resume normal GC;
5. avoid duplicate canonical RecordingSegment/RecordingLocation creation.

No persistent PrebufferFragment table is required solely for this reconstruction.

## GC

GC applies only to ephemeral finalized tmpfs fragments not required by any active promotion window.

Conceptual:

~~~text
delete when:
  finalized
  AND fragment.end_at < buffer_keep_after
  AND not required by active RecordingTrigger window
  AND not currently promoting
~~~

Before unlink, re-check eligibility.

Under tmpfs pressure:

1. delete oldest eligible ephemeral fragments;
2. never delete a protected/promoting fragment;
3. expose pre-roll degraded/critical health if capacity is insufficient;
4. do not fabricate coverage.

## Comparison POC

POC-03 should still record comparison evidence for startRecordTask and ordinary GOP-ring startRecord where practical, because a future ZLM release may improve them.

But candidate C wins only if the POC shows:

- stable requested pre-roll coverage;
- no duplicate recorder;
- normal on_record_mp4 path;
- bounded tmpfs;
- predictable promotion;
- acceptable hook/file churn.

## POC-04 overlap semantics

The effective promotion window is derived from active RecordingTriggers.

Example:

~~~text
Event A:
  T=20:00:10
  required_end=20:00:20

Event B:
  T=20:00:17
  required_end=20:00:27

effective promotion end -> 20:00:27
~~~

No ZLM recorder command is issued for either extension.

A third update/event may extend the same window again.

All Events/Triggers remain individually queryable.

## Acceptance direction

Candidate C can be frozen only after real execution demonstrates:

1. one ZLM recorder remains active for the camera;
2. requested pre-roll is covered across fragment boundaries;
3. overlapping Events extend promotion only, not recorder count;
4. normal ZLM hooks provide usable actual file timing;
5. POC restart/reconciliation can recover ephemeral finalized fragments;
6. tmpfs usage is bounded and measured;
7. H.264 with at least two GOP intervals works;
8. H.265 is tested where the available ZLM/FFmpeg test stack supports it;
9. promotion never exposes *.partial as canonical AVAILABLE media;
10. source/camera RTSP connection count remains unchanged.

Until those pass, this document remains a candidate and must not be treated as frozen implementation.

## Non-goals

Do not add for V1 merely to solve pre-roll:

- a custom compressed packet ring;
- a custom media muxer;
- a permanent second recorder;
- a PrebufferFragment database table;
- a RecordingSession table;
- synchronous first-segment concatenation;
- exact frame-level trim during event ingestion.
