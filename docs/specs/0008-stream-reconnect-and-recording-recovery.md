# Spec 0008 — Stream Loss, Runtime Recovery, and Recording Reconciliation

Status: **accepted**

## Goal

Define how zero-nvr behaves when a camera stream disappears, ZLMediaKit reconnects, a recording is interrupted, or the zero-nvr control plane restarts.

Core rule:

> ZLMediaKit owns media transport, source pulling, reconnect behavior, and recorder runtime. zero-nvr owns product intent, health projection, historical catalog reconciliation, and user-visible gap semantics.

zero-nvr must not grow a second RTSP reconnect engine or packet-level media state machine beside ZLMediaKit.

See [Project Baseline](../PROJECT_BASELINE.md).

## Ownership boundary

### ZLMediaKit owns

- RTSP/source pull lifecycle;
- protocol-level timeout and reconnect behavior;
- runtime stream registration/unregistration;
- media-track and codec runtime;
- recorder start/stop execution;
- physical MP4/fMP4 finalization;
- runtime media state exposed through ZLM APIs/hooks.

### zero-nvr owns

- whether a camera is enabled;
- desired recording policy;
- mapping Camera/StreamProfile to ZLM media identifiers;
- current product health derived from ZLM observations;
- RecordingSegment catalog entries;
- Event/SystemEvent state;
- Timeline/Gap projection;
- reconciliation after lost hooks or control-plane downtime;
- alerts when media remains unavailable.

### zero-nvr does not own

- packet starvation detection;
- RTP/RTCP monitoring;
- RTSP reconnect backoff;
- codec-level reconnect handling;
- a custom STREAMING/DEGRADED/RECONNECTING transport state machine;
- a second long-lived camera puller.

If ZLM exposes useful reconnect/runtime details, zero-nvr may surface them as diagnostics without becoming their owner.

## Desired state and observed state

The control plane tracks desired product state such as:

```text
camera.enabled = true
recording_policy = CONTINUOUS
```

The ZLM adapter observes current runtime facts such as:

```text
stream_registered
stream_missing
recording_active
media_server_unreachable
```

Reconciliation compares desired and observed state and performs only the minimum supported ZLM API operation required to converge.

It must remain idempotent.

## Product health projection

Recommended product-facing camera/media health:

```text
ONLINE
DEGRADED
OFFLINE
DISABLED
```

These are product health summaries, not an independently implemented media transport state machine.

Examples:

- stream present and expected recorder active -> ONLINE;
- ZLM reachable but one required stream/recorder is unavailable -> DEGRADED;
- required source remains absent beyond the configured health threshold -> OFFLINE;
- camera administratively disabled -> DISABLED.

A temporary ZLM reconnect may be displayed in diagnostics when ZLM exposes it, but zero-nvr does not schedule the reconnect itself.

## Recording continuity

Recording media truth comes from actual finalized media.

A source/runtime interruption may cause:

```text
[ RecordingSegment A ]   gap   [ RecordingSegment B ]
```

zero-nvr must not stretch timestamps or fabricate frames to hide the interruption.

Segment boundaries are not inferred from the nominal 300-second target. Use actual start/end/duration metadata from the normal hook/catalog path, with reconciliation fallback when a hook is missed.

## Gap projection

Gap is not a stored authoritative media row.

For a requested time range:

```text
Gap = requested wall-clock interval - merged available recording coverage
```

When reliable system/runtime evidence exists, a projected gap may expose a reason such as:

```text
source_unavailable
media_server_restart
storage_unavailable
missing_media
purged
not_scheduled
no_event_recording
```

The absence of a diagnostic reason must not change the authoritative recording coverage.

## Runtime/server restart

If ZLM restarts or media continuity cannot be proven:

- finalized media before the restart remains cataloged;
- post-recovery media begins from its real timestamp;
- any real missing interval appears as a gap;
- zero-nvr re-applies desired product configuration only through supported adapter operations;
- do not append recovered media to an old file merely to preserve a nominal segment cadence.

## zero-nvr API / worker / database outage

The media hot path is:

```text
Camera -> ZLMediaKit -> local recording filesystem
```

The database is not in that hot path.

Where practical, a short FastAPI/worker/database outage must not terminate an already-running ZLM recording.

After recovery:

```text
load desired state
-> query ZLM runtime
-> reconcile stream/recording state
-> reconcile finalized media catalog
-> resume normal hooks/tasks
```

A missed `on_record_mp4` hook is therefore recoverable.

## Event arrival during video outage

An Event/RecordingTrigger may arrive while video is unavailable.

zero-nvr still:

- persists the event/trigger;
- keeps its real timestamps;
- applies the recording intent semantics;
- does not fabricate pre-roll;
- exposes degraded/missing video coverage;
- resumes recording when media becomes available if the effective recording intent still requires it.

## Reconciliation sources

Normal path:

```text
ZLM on_record_mp4
-> RecordingSegment / RecordingLocation
```

Recovery sources may include:

1. ZLM recorder/file listing APIs where supported;
2. known recording-root scan using zero-nvr path identity rules;
3. ffprobe only as a recovery fallback when authoritative metadata is unavailable.

Do not continuously ffprobe every normal segment.

## Diagnostics

Useful diagnostics include:

- ZLM reachable/unreachable;
- expected stream present/missing;
- current recorder active/inactive;
- last known media registration time;
- most recent finalized segment time;
- most recent reconciliation time/result;
- current camera health;
- recent system health transitions.

Persist meaningful transitions/events, not high-frequency transport telemetry.

## Acceptance tests

1. Camera source disappears while continuous recording is active:
   - ZLM performs its configured reconnect behavior;
   - zero-nvr does not start its own RTSP retry engine;
   - real missing coverage appears as a timeline gap.

2. Camera recovers:
   - ZLM stream returns;
   - recording resumes according to desired policy;
   - post-recovery media uses actual timestamps.

3. FastAPI restarts during an active ZLM recording:
   - the already-running recorder is not deliberately stopped;
   - after API recovery, runtime state converges through reconciliation.

4. Database is temporarily unavailable:
   - existing ZLM recording continues where practical;
   - missed catalog work is recovered later.

5. An `on_record_mp4` hook is intentionally dropped:
   - reconciliation discovers the finalized recording;
   - duplicate RecordingSegment rows are not created.

6. ZLM restarts:
   - zero-nvr detects the runtime loss;
   - desired configuration is restored;
   - any true recording gap remains visible.

7. Event arrives during source outage:
   - Event and RecordingTrigger remain queryable;
   - unavailable pre-roll/video is reported rather than fabricated.

## Invariants

1. ZLMediaKit is the owner of camera media transport/reconnect runtime.
2. zero-nvr does not implement a competing RTSP reconnect/packet-monitor state machine.
3. Recording files and catalog are eventually consistent and recoverable.
4. The database is not placed in the live media write path.
5. Real gaps are preserved as real wall-clock gaps.
6. Health state is a product projection over adapter observations.
7. Reconciliation is idempotent and must not create duplicate pullers, recorders, or catalog rows.
8. ffprobe is a recovery tool, not the normal per-segment indexing path.
9. A control-plane restart must not intentionally stop healthy ZLM recording unless a configuration change requires it.
10. Non-obvious recovery behavior must be documented and tested.
