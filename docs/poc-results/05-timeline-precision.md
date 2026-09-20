# POC-05 — Timeline Precision

Result: **PASS**

## Purpose

Validate that historical playback uses actual finalized media coverage on an absolute wall-clock timeline rather than assuming fixed segment duration or trusting raw ZLM Hook start timestamps without normalization.

## Harness

~~~text
poc/zlm-recording/scripts/run-timeline-playback.sh
~~~

The passing rerun is GitHub Actions run `35490899825`, job `POC 05`.

## Tested versions

~~~text
GitHub Actions run: 35490899825
job: POC 05

ZLMediaKit:
  branch: master
  commit: b794772
  buildTime: 2026-09-20T02:21:00

Docker Engine: 28.0.4
Docker Compose: v2.38.2
runner: Ubuntu 24.04.5 / linux amd64
~~~ 

## Test design

1. Start one ZLM-recorded H.264 stream.
2. Wait for several normally finalized segments.
3. SIGKILL MediaMTX.
4. Wait for ZLM `on_stream_changed(regist=false)`.
5. Hold the **ZLM-observed source-lost state** for eight seconds.
6. Restart MediaMTX.
7. Wait for ZLM `on_stream_changed(regist=true)`.
8. Wait for post-recovery recording segments.
9. Normalize timestamps only **within each proven continuous ZLM media session**.
10. Build merged recording ranges and the real Gap.
11. Resolve an Event marker through the same wall-clock resolver.
12. Exercise DST and camera-clock normalization invariants.

## Raw Hook timing finding

The first runtime attempt invalidated the assumption:

~~~text
segment.start_at = on_record_mp4.start_time
segment.end_at   = start_at + time_len
~~~

as a universally precise canonical wall-clock coverage rule.

Current ZLM creates the MP4 file on its first received frame, while the muxer may discard leading non-keyframes until a usable keyframe. Therefore the first raw Hook boundary in a continuous recording session can be early by about one GOP.

Passing rerun example:

~~~text
raw first same-session boundary delta ≈ 2.042 s
following raw steady-state deltas     ≈ 0.040 s
~~~

## Accepted V1 timing rule

For a **proven continuous ZLM media/recording session**:

~~~text
for segment N when segment N+1 exists:

  normalized_end(N)   = raw_hook_start(N+1)
  normalized_start(N) = normalized_end(N) - actual_duration(N)

where:
  actual_duration = on_record_mp4.time_len
~~~

The final currently-known segment in a session uses the raw Hook start + actual duration fallback until a stronger next/close boundary exists.

Critical rule:

> Never normalize across a ZLM source unregister/re-register boundary.

Session boundaries come from ZLM media runtime evidence such as `on_stream_changed`, not from a guessed time-gap threshold.

Raw Hook metadata should remain available for reconciliation/diagnostics; normalization is a product timing projection.

## Evidence

### ZLM-observed outage

~~~text
requested outage start:
  2026-09-20T05:09:24.944788Z

ZLM source lost:
  2026-09-20T05:09:27.058654Z

ZLM source recovered:
  2026-09-20T05:09:40.092014Z

ZLM-observed source-lost duration:
  ≈ 13.033 s
~~~

The resulting canonical recording coverage was:

~~~text
range 1:
  2026-09-20T05:08:56.042Z
  ..
  2026-09-20T05:09:24.400Z

Gap:
  2026-09-20T05:09:24.400Z
  ..
  2026-09-20T05:09:41.041Z
  duration ≈ 16.641 s
  reason = source_lost

range 2:
  2026-09-20T05:09:41.041Z
  ..
  2026-09-20T05:10:08.960Z
~~~

The Gap midpoint resolved as:

~~~text
status = gap
previous_at = 2026-09-20T05:09:24.400Z
next_at     = 2026-09-20T05:09:41.041Z
~~~

No timestamp stretching was used to hide the outage.

### Same-session normalization

Representative normalized boundary deltas:

~~~text
0.040 s
0.040 s
0.000 s

post-recovery:
0.040 s
0.000 s
~~~

The test tolerance was 1.25 seconds, preserving the raw deltas in evidence.

Representative corrections:

~~~text
pre-session first segment:
  +2042 ms

post-session first segment:
  +1041 ms

steady-state:
  ~+40 ms
~~~

This is exactly the GOP/startup bias that the first failed attempt exposed.

### Partial segment

The source-loss sequence produced and preserved a real short segment:

~~~text
duration ≈ 0.400 s
~~~

The Timeline did not round/stretch it to the configured target duration.

### Event marker

A marker at:

~~~text
2026-09-20T05:09:10.115600Z
~~~

resolved to the expected segment at:

~~~text
offset ≈ 6.0756 s
status = playable
~~~

### DST

The repeated Los Angeles fall-back wall-clock time was preserved correctly:

~~~text
2026-11-01T08:30:00Z
-> 2026-11-01T01:30:00-07:00
fold=0

2026-11-01T09:30:00Z
-> 2026-11-01T01:30:00-08:00
fold=1
~~~

Both round-tripped to the original UTC instants.

### Camera clock offset

A synthetic device offset of:

~~~text
+5000 ms
~~~

normalized back to canonical UTC without shifting RecordingSegment media truth.

## Artifact

~~~text
GitHub Actions run: 35490899825
artifact: poc-05-evidence
artifact id: 10598254986
SHA256: 961320410b2389a21f72d9bf5431c84badf3ee1ed769da0b69238b5f46725cda
~~~ 

Primary file:

~~~text
runtime/timeline-playback-evidence.json
~~~

## Known limitations

- Current raw `on_record_mp4.start_time` has second-level wall-clock characteristics and startup/keyframe bias; it is not used blindly as final canonical coverage.
- The tail segment of an open/current session has no next segment boundary yet and therefore temporarily uses raw Hook start + actual duration. It may be refined when a later boundary becomes known.
- The measured source-loss Gap is longer than the ZLM-observed unregister-to-register interval because actual usable recorded media can stop before unregister detection and resume after keyframe/media recovery. This is correct: Timeline represents media coverage, not merely control-state duration.
- The POC uses a deterministic synthetic H.264 source; the timing rule is codec-independent in the domain model, but additional device diversity remains normal integration validation.

## Architecture impact

**Accepted.**

V1 Timeline timing is frozen as:

~~~text
actual finalized duration
+
ZLM-observed continuity sessions
+
next proven segment boundary normalization within a session
+
real Gap across unregister/reconnect
~~~

Do not:

- assume every segment is exactly 300 seconds;
- use filename order alone;
- normalize across source-loss boundaries;
- invent Gap rows in the database;
- run ffprobe on every normal finalized segment merely to repair raw Hook wall-clock bias.

Timeline remains a projection over canonical RecordingSegments + Events/system runtime evidence.
