# POC-05 — Timeline Precision

Result: **NOT RUN**

## Purpose

Validate that historical time is derived from actual finalized RecordingSegment coverage rather than assumed fixed file length.

## Harness

~~~text
poc/zlm-recording/scripts/run-timeline-playback.sh
~~~

The runner:

1. starts one ZLM-recorded H.264 stream;
2. waits for at least three finalized segments;
3. sends SIGKILL to MediaMTX, producing a real source outage;
4. keeps the source unavailable for about eight seconds;
5. restarts MediaMTX and lets ZLM reconnect;
6. waits for post-recovery segments;
7. projects recording ranges and the real source-loss Gap from hook-indexed segment times.

## Required checks

- normal segment boundaries remain continuous within the documented ZLM hook timestamp granularity;
- the deliberate source outage becomes a real positive Gap;
- no timestamp stretching hides the outage;
- the outage sequence must actually produce at least one partial/non-target finalized segment, and that segment keeps its real duration;
- an Event marker inside a segment resolves through the same wall-clock resolver to the expected segment and relative media offset;
- UTC -> America/Los_Angeles -> UTC round-trip survives the 2026 DST fall-back repeated hour;
- repeated local wall-clock time remains distinguished by UTC offset/fold;
- a synthetic +5000 ms camera-clock offset normalizes back to canonical UTC without shifting RecordingSegment timestamps.

## Timestamp tolerance

The POC records every raw boundary delta.

The first harness allows a small continuity tolerance because current ZLM on_record_mp4 start_time metadata has limited absolute-time granularity. The raw gap/overlap is never erased from evidence.

If measured jitter is too large for reliable product timeline behavior, the architecture must add a stronger timestamp derivation source rather than pretending fixed-duration segments are exact.

## Expected evidence

~~~text
poc/zlm-recording/runtime/timeline-playback-evidence.json
poc/zlm-recording/runtime/timeline-docker-compose.log
poc/zlm-recording/runtime/poc.db
~~~

Fields include:

~~~text
segments
boundary_deltas
recording_ranges
projected_gap
partial_or_non_target_durations
event_marker
dst_roundtrip
camera_clock_normalization
~~~

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

## Architecture impact

Pending execution.
