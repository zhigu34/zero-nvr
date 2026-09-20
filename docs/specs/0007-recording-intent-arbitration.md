# Spec 0007 — Recording Intent Arbitration

Status: **accepted**

## Goal

Define how multiple business reasons to record one camera combine without starting duplicate recorder processes.

Core rule:

> A camera has one normal ZLMediaKit recording runtime. Recording reasons are additive policy/intents that decide whether that runtime should be active; they are not separate recorders.

## Recording reasons

V1 reasons include:

```text
CONTINUOUS
SCHEDULE
EVENT
MANUAL
```

DISABLED means the policy does not request normal recording.

EVENT is backed by one or more RecordingTriggers.

## Effective recording requirement

Conceptually:

```text
should_record =
    continuous_enabled
 OR schedule_window_active
 OR active_event_trigger_window
 OR manual_recording_active
```

When `should_record` changes:

```text
false -> true
    request ZLM recorder start if not already active

true -> true
    keep current recorder; do not restart

true -> false
    request ZLM recorder stop at the appropriate boundary
```

All operations are idempotent.

## One recorder rule

Do not create:

- one FFmpeg process for continuous;
- another recorder for events;
- another recorder for manual mode.

Instead:

```text
many reasons
   -> one recording decision
   -> one ZLM recorder
```

This prevents duplicated camera bandwidth, duplicated files, and recorder races.

## Continuous

CONTINUOUS keeps recording requested while the camera/policy is enabled.

Events occurring during continuous recording:

- remain independent Event markers;
- may create RecordingTrigger/product linkage;
- may protect/annotate the relevant time range;
- do not start a second recorder;
- do not create a duplicate event MP4 unless the user explicitly exports a clip.

## Schedule

SCHEDULE is active only inside configured wall-clock schedule windows.

Schedules carry an explicit timezone.

DST/time corrections are handled by schedule evaluation, while persisted recording timestamps remain UTC.

Schedule entry/exit changes only the schedule recording reason. If another reason remains active, the recorder continues without restart.

## Manual

MANUAL begins on an explicit authorized user/API action and ends on explicit stop or an optional configured timeout.

Stopping MANUAL removes only the manual reason.

If CONTINUOUS/SCHEDULE/EVENT still requires recording, the recorder remains active.

## Event

EVENT recording is represented by RecordingTrigger windows.

Example:

```text
Event A:
  planned_start = 20:00:00
  planned_end   = 20:00:20

Event B arrives at 20:00:17:
  effective event recording requirement extends to 20:00:27
```

Event A and Event B remain separate Event/Trigger records.

The physical recording runtime remains one recorder.

## RecordingTrigger aggregation

For a camera, effective event coverage is the union of active trigger windows.

The system may efficiently track the current latest event deadline, but canonical trigger rows remain independently queryable.

Closing one trigger must not stop recording while another trigger/reason still requires it.

## Pre-roll

The product semantics may request about 10 seconds of EVENT_ONLY pre-roll.

The physical mechanism is not part of recording-requirement arbitration.

It is resolved by the design-freeze POC using mature ZLM capabilities.

Recording arbitration only requests/records:

- desired pre-roll;
- desired post-roll;
- planned trigger window;
- whether pre-roll coverage was actually available.

Do not encode a specific tmpfs/rolling-MP4 implementation into the intent state model.

## Derived active recording interval

For reasoning and UI, zero-nvr may refer to a continuous interval during which `should_record=true`.

This is a derived interval, not a required persisted entity.

It may span several physical RecordingSegments because of:

- normal segmentation;
- source outage/recovery;
- ZLM restart;
- storage interruption;
- profile reconfiguration.

Actual RecordingSegment times remain media truth. If a feature later proves that a persisted logical interval adds real product value, introduce it through a separate schema/ADR rather than making it a V1 prerequisite.

## Interaction with source outages

Recording reason and media availability are different facts.

If should_record remains true while source media disappears:

- do not clear CONTINUOUS/SCHEDULE/EVENT/MANUAL merely because video is unavailable;
- actual finalized media ends at its real time;
- timeline shows a gap;
- when ZLM media returns, recording desired state is reconciled.

zero-nvr does not run a second reconnect engine.

## Interaction with storage failure

A local recording target failure does not silently redirect recording to cloud/archive storage.

Recording reason may remain active while recording capability is degraded/critical.

The host storage or configured local target must recover/change before media can be reliably written again.

## Restart recovery

After API/worker restart:

1. load durable policy/manual/event-trigger state;
2. evaluate current schedule/time windows;
3. query ZLM actual recorder state;
4. reconcile desired recorder state;
5. do not blindly restart an already-running recorder.

Manual/event state that must survive restart is persisted.

Derived continuous/schedule activity may be recomputed from policy/time.

## Concurrency

Recording arbitration for one camera must be serialized enough that simultaneous:

- event update;
- schedule boundary;
- manual click;
- policy change

cannot cause duplicate start/stop commands or lose an active reason.

SQLite and PostgreSQL implementations may use different locking mechanics behind one service contract.

Do not build a distributed consensus/lease system for a single-host V1.

## UI

Recording state should explain both:

```text
why recording is requested
and
whether media is actually being written
```

Example:

```text
Reasons: CONTINUOUS + EVENT(person)
Recorder: active
Storage: OK
```

or:

```text
Reasons: EVENT(person)
Recorder: unavailable
Media: source offline
```

## Acceptance tests

1. Continuous + event:
   - event does not restart recorder;
   - Event marker links to existing footage.

2. Schedule ends while event active:
   - recorder stays active until event/post-roll ends.

3. Manual starts during continuous:
   - no second recorder starts.

4. Manual stops while continuous active:
   - recorder continues.

5. Two overlapping events:
   - one recorder remains;
   - latest required end time is respected;
   - both Events remain separate.

6. API restart:
   - desired reasons are reconstructed;
   - already-running ZLM recorder is not duplicated.

7. Source outage:
   - recording reasons remain logically active;
   - real media gap is preserved.

8. Storage failure:
   - no automatic cloud hot-recording fallback occurs.

## Invariants

1. One camera has at most one normal ZLM recording runtime.
2. Recording reasons are additive and independently removable.
3. A change of reason does not restart the recorder while another reason remains active.
4. Events never require a duplicate event recorder during existing continuous/scheduled/manual recording.
5. RecordingTrigger is the canonical EVENT recording request/evidence model.
6. Pre-roll physical implementation is separate and POC-gated.
7. Media availability does not rewrite business recording reasons.
8. Arbitration is idempotent and serialized per camera.
