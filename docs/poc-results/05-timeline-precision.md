# POC-05 — Timeline Precision

Result: **PASS**

## Purpose

Validate canonical historical wall-clock coverage from actual finalized media, including normal rollover, source loss/reconnect, partial segments, Event markers, DST, and camera-clock normalization.

## Harness

~~~text
poc/zlm-recording/scripts/run-timeline-playback.sh
~~~

The test records actual ZLM `on_stream_changed` RTSP registration transitions and never guesses the continuity split solely from an external process-kill timestamp.

## Tested versions

~~~text
GitHub Actions run: 35490737812
job: POC 05
head SHA: 20ae4741b480269bb61b69a8b4b123a46163af02
ZLMediaKit:
  branch: master
  commit: b794772
  buildTime: 2026-09-20T02:21:00
managed recording mode: fMP4
~~~

## Evidence

### Proven source outage

ZLM observed:

~~~text
source lost:      2026-09-20T05:05:38.248876Z
source recovered: 2026-09-20T05:05:51.289988Z
observed lost duration ≈ 13.041 s
~~~

Projected playable ranges ended/began at:

~~~text
pre-outage end:  2026-09-20T05:05:35.280000Z
post-outage start: 2026-09-20T05:05:52.040000Z
projected Gap ≈ 16.760 s
reason = source_lost
~~~

The extra interval relative to register-state duration is real unavailable media around recorder/keyframe/reconnect boundaries. It was preserved as a Gap rather than hidden by a generic tolerance.

Gap midpoint resolution returned:

~~~text
status = gap
previous_at = 2026-09-20T05:05:35.280000Z
next_at     = 2026-09-20T05:05:52.040000Z
~~~

### Same-session timing normalization

Raw current-ZLM Hook boundaries showed about 40ms normal jitter and one approximately 1.04s GOP-related bias after reconnect.

Accepted resolver inside a **proven continuous ZLM session**:

~~~text
segment N actual muxed duration = D
next proven segment file-creation boundary = B

segment N:
  ended_at   = B
  started_at = B - D
~~~

Normalized same-session boundary deltas in this run:

~~~text
~40ms
~40ms
0ms
~41ms
0ms
~~~

A source unregister/reconnect always creates a new timing session; the resolver never uses a post-reconnect boundary to normalize a pre-disconnect segment.

A real partial pre-outage tail was retained at approximately 280ms instead of being expanded to the nominal segment target.

### Event / timezone / clock

- Event marker resolved inside the expected segment at about 6.076s media offset.
- UTC -> America/Los_Angeles -> UTC survived the 2026 fall-back repeated 01:30 hour, preserving distinct `-07:00` and `-08:00` offsets/fold.
- a synthetic +5000ms camera clock offset normalized back to canonical UTC without shifting RecordingSegment media time.

## Primary artifact

~~~text
GitHub Actions run: 35490737812
artifact: poc-05-evidence
artifact id: 10599201935
runtime/timeline-playback-evidence.json
~~~

## Architecture impact

**Accepted:** raw `on_record_mp4.start_time` is retained as source evidence but is not blindly used as canonical media coverage.

The ZLM adapter resolves canonical start/end inside a proven continuity session from actual muxed duration plus a stronger next-boundary anchor. ZLM stream unregister/re-register events split timing sessions. Tail/ambiguous cases use explicit stronger stop/loss evidence or a documented fallback; they are never bridged across a real outage.

ffprobe remains a recovery/ambiguity fallback rather than a normal successful-Hook dependency.
