# Spec 0008 — Stream Loss, Reconnect, and Recording Recovery

Status: **accepted**

## Goal

Define how zero-nvr detects source-stream loss, closes interrupted media safely, retries camera pull, preserves RecordingIntent/RecordingSession semantics, restarts formal segmentation, and exposes the resulting gap on the historical timeline.

Core rule:

> Network/media transport recovers independently from recording business intent. A source loss may split physical MP4 files without ending the logical RecordingSession.

## Layer separation

Do not conflate:

1. camera/protocol session — RTSP connection/session, vendor SDK handle, etc.;
2. ZLMediaKit runtime stream — transient media source/proxy state;
3. RecordingSegment — one finalized physical formal MP4;
4. RecordingSession — one uninterrupted business interval in which at least one RecordingIntent requires recording.

A transport reconnect rebuilds protocol/runtime state where required.

A real media break always causes post-recovery footage to use a new physical RecordingSegment.

A transport reconnect does not end RecordingSession while RecordingIntent still requires recording.

## Runtime state machine

```text
STREAMING
   |
   | temporary media starvation/jitter
   v
DEGRADED
   |
   +-- media resumes while runtime stream remains valid
   |      -> STREAMING
   |      -> current physical RecordingSegment may continue
   |
   +-- source/runtime stream confirmed lost
          |
          v
RECONNECTING
          |
          +-- finalize interrupted physical segment
          |      completion_reason = source_lost
          |
          +-- retry source pull
                 |
                 +-- success -> STREAMING + new physical segment
                 |
                 +-- prolonged failure -> OFFLINE
                                         background retry continues
```

DEGRADED is a transient runtime condition. It is not automatically a timeline gap unless actual media timestamps show missing footage.

## Detection principle

Do not classify stream loss only from a fixed wall-clock threshold such as "3 seconds".

The decisive question is whether the media source/runtime stream is still valid and whether the recorded media timeline remains continuous.

Examples:

- packet jitter while the same source remains alive may continue the current segment;
- explicit source unregister/close/fatal pull error means physical continuity is broken;
- reconnecting after a lost source always starts a new physical file.

Timeouts remain configurable runtime/health thresholds rather than business truth.

## ZLMediaKit integration boundary

zero-nvr treats ZLMediaKit as transient media runtime.

For RTSP pull proxy, the deployed adapter should use ZLMediaKit pull timeout/retry controls and preserve a stable logical camera/media-plane key while allowing the underlying player/protocol connection to be rebuilt.

Relevant runtime signals may include:

- on_stream_changed registration/unregistration;
- pull-proxy close/error state;
- media-server restart/health state;
- recorder/finalization callbacks.

on_stream_none_reader must not be used as a camera-disconnect signal because it represents a stream with no readers.

Exact hooks/options are implementation details and must be verified against the deployed ZLMediaKit version.

## Reconnect policy

Recommended V2 behavior:

```text
camera enabled
    -> keep retrying indefinitely
```

Retry scheduling should prevent retry storms.

Conceptual policy:

```text
fast initial retry
then exponential backoff + per-camera jitter
cap at configurable maximum
reset retry state after stable recovery
```

A reasonable cap may be in the 30–60 second range, but the exact algorithm is runtime tuning rather than a domain invariant.

## Offline classification

RECONNECTING and OFFLINE are health/UI states, not different media-correctness models.

Initial configurable default:

```text
offline_after_seconds = 30
```

Meaning:

- before threshold: degraded/reconnecting;
- after threshold: offline;
- background retry still continues while camera remains enabled.

This threshold does not rewrite RecordingSegment timestamps.

## Physical segment behavior

When source continuity is confirmed lost while a formal MP4 is open:

1. stop accepting media into the old file;
2. finalize/close it as safely as possible;
3. persist actual ended_at;
4. record completion_reason = source_lost;
5. never append post-reconnect media into the old MP4.

If finalization fails, mark integrity/recovery state explicitly and let reconciliation handle the partial object.

## Segment clock after recovery

A real media discontinuity resets the physical formal segment cadence.

After media resumes at R:

```text
new segment starts = R
next boundary      = R + formal_record_segment_seconds
```

Example:

```text
segment A
14:00:00 -------- 14:02:15

gap
14:02:15 -------- 14:02:23

recovered cadence
14:02:23 -------- 14:07:23
14:07:23 -------- 14:12:23
```

Do not create an artificial short segment at the old planned boundary just to restore the pre-failure clock.

This is an explicit exception to the healthy-session rule: RecordingIntent changes do not reset cadence, but a real media discontinuity does.

## RecordingSession behavior

Source loss does not remove RecordingIntent.

```text
continuous intent:
----------------------------------------

RecordingSession:
----------------------------------------

physical media:
[======= A =====]        [======= B =====]
                 gap
```

If one or more RecordingIntents remain active while source media is unavailable:

- keep the same RecordingSession;
- keep active intents unchanged;
- record the real media gap;
- resume into a new RecordingSegment after recovery.

RecordingSession ends only when the effective active-intent set becomes empty according to Spec 0007.

## Event recording during outage

An event may arrive from an independent source while video is unavailable.

In that case:

- persist DetectionEvent;
- maintain event RecordingIntent lifecycle normally;
- keep Event Marker on the timeline;
- request/maintain formal recording intent;
- represent unavailable video time as a gap;
- resume capture when media returns if any intent is still active.

Never fabricate missing pre-roll or duplicate frames to hide the outage.

## Idle prebuffer during disconnect

If source loss happens during IDLE_PREBUFFER:

- finalize/reconcile the current temporary fragment if possible;
- do not create a formal RecordingSegment merely because of disconnect;
- pause prebuffer production;
- after recovery start a fresh prebuffer fragment;
- later pre-roll degradation must be observable if required footage is unavailable.

## Runtime/server restart

When media continuity cannot be proven across a runtime restart:

```text
completion_reason = runtime_restart
```

After recovery:

- reconstruct active RecordingIntents;
- preserve/reconcile RecordingSession;
- create a new physical segment from actual media recovery time;
- show the true gap.

Never stretch timestamps across a restart.

## Codec/track discontinuity

If codec/track parameters change such that the same file cannot safely continue:

- finalize current segment;
- create a new segment;
- completion_reason = media_discontinuity;
- keep RecordingSession alive if intents remain active.

## Timeline representation

Known outage interval:

```text
gap.reason = source_lost
```

Example:

```text
14:00:00      14:02:15   14:02:23       14:07:23
 [segment A]      | gap |   [segment B]
                      ^
                 source_lost
```

At close zoom show the true gap and its reason.

At wide zoom Spec 0006 may visually smooth a sub-pixel gap, but authoritative gap data remains unchanged.

## Playback over outage gaps

Single-camera playback follows Spec 0006:

```text
skip_gaps = on
  -> jump to next playable absolute time

skip_gaps = off
  -> global time continues
  -> player shows source_lost/no-recording state
```

Multi-camera playback never skips global time solely because one selected camera has a source-loss gap while another selected camera has media.

## System connectivity history

Infrastructure failures are not DetectionEvents.

Conceptual system/runtime history:

```text
camera_id
kind = source_connectivity
started_at
ended_at
state
reason
details
```

Useful actions/states:

```text
stream_degraded
stream_lost
reconnect_started
reconnect_succeeded
camera_offline
camera_online
recording_segment_interrupted
```

This data may support health, diagnostics, timeline gap explanations, and optional system markers.

## UI behavior

Live/Device states:

```text
online
degraded
reconnecting
offline
disabled
```

Historical gap reasons remain distinct:

```text
source_lost
runtime_restart
storage_failure
missing_media
purged
not_scheduled
no_event
```

A camera can be online now while its historical timeline still contains old outage gaps.

## Recovery diagnostics

Expose enough diagnostics to answer:

- when was source media last received?
- when did runtime declare loss?
- how long was reconnecting?
- what retry attempt recovered?
- which segment was interrupted?
- did MP4 finalization succeed?
- what absolute media time resumed?
- was RecordingSession preserved?
- was pre-roll coverage degraded?

## Acceptance tests

1. brief jitter without runtime stream loss:
   - current segment continues if continuity remains valid;
   - no fake gap appears;

2. explicit source loss during formal recording:
   - current MP4 closes early;
   - completion_reason = source_lost;
   - finalized file is independently playable when close succeeds;

3. recovery:
   - new physical file begins at actual recovery time;
   - new 5-minute cadence anchors at recovery;
   - no append to old MP4;

4. continuous intent across outage:
   - one RecordingSession remains;
   - timeline shows true source_lost gap;

5. event/manual overlap across outage:
   - RecordingIntents remain correct;
   - recovery does not create duplicate intent/session;

6. prolonged outage:
   - health transitions reconnecting -> offline;
   - retries continue;

7. multi-camera playback:
   - one camera gap does not shift others;
   - strict barrier excludes legitimate-gap channels;

8. restart:
   - interrupted segment uses runtime_restart;
   - active intents/session semantics are reconstructed;

9. codec discontinuity:
   - new segment uses media_discontinuity.

## Invariants

1. Protocol runtime, ZLM runtime stream, RecordingSegment, and RecordingSession are distinct layers.
2. Real source loss closes the current physical RecordingSegment.
3. Post-reconnect media is never appended to the old MP4.
4. Real media discontinuity resets physical formal segment cadence from actual recovery time.
5. Source loss does not end RecordingSession while any RecordingIntent remains active.
6. Source loss does not cancel active RecordingIntents.
7. on_stream_none_reader is not a camera-disconnect signal.
8. Fixed timeout thresholds are health/runtime tuning, not the definition of media continuity.
9. Offline state does not stop background reconnect while the camera remains enabled.
10. Historical playback shows the real gap and reason; timestamps are never stretched to hide it.
11. Infrastructure connectivity events are not DetectionEvents.
12. Idle-prebuffer gaps remain observable and are never fabricated over.
13. Runtime restart/discontinuity is explicit through completion_reason.
14. Recovery is idempotent and serialized per camera to avoid duplicate pullers/recorders.
15. Non-obvious reconnect/finalization/recovery behavior requires comments per Development Guidelines.

## Time-source reference

Reconnect/offline elapsed timers use monotonic runtime time, while persisted outage/segment timestamps use canonical UTC. A camera clock must never become the authority for source-loss gap placement. See [Spec 0009 — Canonical Time, Camera Clock Offset, and Timezone Handling](0009-time-and-camera-clock.md).
