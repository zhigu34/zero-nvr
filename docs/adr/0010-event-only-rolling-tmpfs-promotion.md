# ADR 0010 — EVENT_ONLY Uses One Rolling ZLM Recorder and Bounded tmpfs Promotion

Status: **accepted**

## Context

EVENT_ONLY needs approximately 10 seconds of pre-roll and post-roll, overlapping Event support, and reliable restart behavior without implementing a custom compressed-video ring or pulling the camera twice.

POC-03/04 compared mature ZLM-native approaches and validated a rolling-fragment design across:

- H.264 with about 2-second GOP;
- H.264 with about 5-second GOP;
- H.265/HEVC;
- ten Event trigger positions per codec/GOP group;
- overlapping Event windows;
- FastAPI stop/restart while ZLM continued recording.

The accepted POC evidence is recorded in GitHub Actions run 35489849518.

## Decision

For an enabled EVENT_ONLY camera, zero-nvr keeps **one normal ZLM recorder** continuously writing short fMP4 fragments into an explicitly bounded tmpfs prebuffer.

~~~text
Camera
  -> ZLMediaKit
  -> one short-fragment fMP4 recorder
  -> bounded tmpfs
  -> finalized on_record_mp4
  -> Event/RecordingTrigger required window
  -> promote overlapping whole fragments
  -> verify + atomic publish
  -> RecordingSegment + RecordingLocation
~~~

Events change promotion/retention state. They do not start another recorder and do not restart the existing recorder.

## Durable vs ephemeral state

Durable product fact:

~~~text
RecordingTrigger
~~~

Ephemeral facts:

~~~text
tmpfs fragment list
current open fragment
promotion-in-progress state
buffer GC state
~~~

V1 does not require a PrebufferFragment or RecordingSession business table.

After control-plane restart, zero-nvr reconstructs required media from:

~~~text
persisted active RecordingTrigger
+ finalized tmpfs filesystem/media scan
+ current ZLM recorder/runtime state
~~~

Hook history is useful evidence but is not required for reconstruction.

## Promotion

Whole finalized fragments overlapping the required Event window are retained.

~~~text
tmpfs source
-> destination *.partial
-> copy
-> size/media verification
-> atomic rename within persistent destination filesystem
-> canonical RecordingSegment + RecordingLocation AVAILABLE
~~~

Exact trimming is deferred to explicit Export jobs.

A fragment needed by multiple Events is promoted once; independent Event/RecordingTrigger rows still remain queryable.

## Buffer sizing and pressure

The tmpfs is a prebuffer, not durable storage.

Capacity is explicit and calculable from enabled EVENT_ONLY camera bitrates and buffer duration.

Under pressure:

1. remove oldest finalized fragments not needed by any active trigger;
2. never delete a protected/promoting fragment;
3. report pre-roll degraded/critical when requested coverage can no longer be guaranteed;
4. never fabricate missing coverage.

Host reboot/power loss may lose unpromoted tmpfs media; already promoted media remains durable.

## Rejected baseline approaches

### startRecordTask

Useful for a fixed clip, but current ZLM creates an independent task/output for each call and exposes no natural extend-one-unknown-duration-task contract. It is not the EVENT_ONLY stateful recorder baseline.

### ordinary startRecord + GOP Ring

Can recover historical GOP content, but the measured raw hook absolute-time semantics are unsuitable as the canonical Event timeline without additional timing logic.

### custom packet ring / second recorder

Rejected as unnecessary wheel reinvention and additional camera/media complexity.

## Consequences

Positive:

- one camera-facing ZLM pull;
- one normal recorder per EVENT_ONLY stream;
- standard ZLM finalize/hook path;
- H.264/H.265 pre-roll demonstrated;
- overlapping events naturally extend promotion, not recorder lifecycle;
- control-plane restart does not require an ephemeral-fragment table.

Trade-offs:

- continuous compressed fragments consume bounded RAM while EVENT_ONLY is enabled;
- whole-fragment promotion intentionally retains some extra media around exact Event boundaries;
- fragment target and tmpfs capacity are deployment/configuration parameters, not universal constants.

## Evidence

See:

- [POC-03 — EVENT_ONLY Pre-roll](../poc-results/03-event-preroll.md)
- [POC-04 — Multi-event Extension](../poc-results/04-multi-event-extension.md)
- [Spec 0003](../specs/0003-rolling-mp4-prebuffer.md)

## Invariants

1. EVENT_ONLY never creates a second permanent camera pull.
2. Event overlap never creates duplicate normal recorders.
3. tmpfs is bounded.
4. RecordingTrigger is durable; fragment inventory is reconstructable runtime state.
5. Only verified/published persistent fragments become canonical RecordingLocations.
6. Promotion failure never deletes the only required prebuffer copy before the failure is surfaced.
