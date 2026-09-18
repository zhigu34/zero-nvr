# Spec 0007 — Recording Intent Arbitration and Mode Composition

Status: **accepted**

## Goal

Define how zero-nvr behaves when continuous, schedule, event, manual, and hybrid recording requirements overlap.

The design must guarantee:

- only one formal media-recording pipeline per camera;
- no recorder restart merely because the reason for recording changes;
- no loss of event/manual/schedule semantics when multiple reasons overlap;
- stable 5-minute segment cadence while recording remains continuously required;
- predictable UI behavior for start/stop/manual controls;
- correct retention claims for shared physical segments.

## Core principle

> Recording reasons are additive. Media recording is shared.

zero-nvr must not model recording modes as mutually destructive states such as:

```text
continuous → manual → event → schedule
```

where one mode replaces another.

Instead:

```text
RecordingIntent(s)
       ↓
RecordingManager
       ↓
one RecordingSession
       ↓
one formal recording pipeline
```

A camera may have several active RecordingIntents at the same time, but it still has only one formal recording runtime and one uninterrupted physical segment clock.

## RecordingIntent

RecordingIntent represents one business reason why a camera must currently remain in formal recording.

Conceptual fields:

```text
id
camera_id
intent_type
source_type
source_id
started_at
planned_end_at
ended_at
state
correlation_id
metadata
created_at
updated_at
```

Initial intent types:

```text
continuous
schedule
event
manual
```

Initial states:

```text
pending
active
post_roll
completed
cancelled
```

Hybrid is a RecordingPolicy composition mode, not a fifth runtime intent type.

## RecordingSession meaning

RecordingSession represents one maximal uninterrupted formal-recording interval for a camera.

It is no longer classified by exactly one recording_type because several recording reasons may overlap during the same uninterrupted media interval.

Conceptual fields:

```text
id
camera_id
started_at
planned_end_at
ended_at
actual_media_started_at
actual_media_ended_at
status
origin_intent_type
created_at
updated_at
```

origin_intent_type records which intent caused an idle camera to enter formal recording. It is diagnostic/history information only; it does not imply that later overlapping intents are secondary or ignored.

A RecordingSession continues as long as at least one RecordingIntent still requires formal recording.

## Active-intent set

For every camera, RecordingManager maintains the effective active intent set:

```text
active_recording_intents
```

The media requirement is:

```text
active_recording_intents != empty
    → FORMAL_RECORDING

active_recording_intents == empty
    → IDLE_PREBUFFER
       (when prebuffer is enabled)
```

The transition from zero active intents to one-or-more active intents creates/starts one RecordingSession.

Adding or removing intents while the set remains non-empty does not restart the recorder and does not reset the formal segment clock.

The transition from one-or-more active intents to zero ends the RecordingSession and returns the camera to idle prebuffer mode.

## Continuous mode

When RecordingPolicy.mode = continuous and the camera/policy is enabled:

```text
continuous intent = active
```

The continuous intent remains active while continuous recording is enabled.

Events during continuous recording:

- create/update DetectionEvent;
- add event markers;
- add event retention claims to affected RecordingSegments;
- do not create another physical recorder;
- do not reset segment cadence;
- do not stop the continuous intent.

Manual recording during continuous recording:

- creates a manual intent for audit/retention/user-visible state;
- does not restart the recorder;
- stopping manual removes only the manual intent;
- continuous recording continues because the continuous intent remains active.

## Schedule mode

A schedule occurrence creates a schedule intent at its start boundary.

At schedule end:

- complete that schedule intent;
- stop formal recording only if no other active intent remains.

Example:

```text
schedule: 08:00 ───────────── 18:00
manual:                    17:55 ───────── 18:30

formal recording:
          08:00 ────────────────────────── 18:30
```

At 18:00 the schedule intent ends, but the RecordingSession remains active because manual recording still requires media.

Starting/ending a schedule must not reset an already-active session's 5-minute segment clock.

## Event mode

Event recording remains governed by Spec 0002.

For an isolated event while no other intent is active:

```text
event at T
pre_roll = P

event intent / RecordingSession logical start = T - P
```

The pre-roll is assembled from PrebufferFragments according to Spec 0003.

While any stateful DetectionEvent remains active, the event intent remains active.

After the last event ends:

```text
event intent
active → post_roll
```

and completes after configured post-roll unless another event extends/cancels that pending completion.

When an event occurs while another intent already keeps formal recording active:

- no new media pipeline starts;
- the event lifecycle still exists;
- event markers are created;
- event retention claims are attached to overlapping RecordingSegments;
- the event intent may exist for lifecycle/audit purposes but does not control the already-running media by itself.

When the event/post-roll ends, removing the event intent stops recording only if no other active intent remains.

## Manual mode / manual recording action

Manual recording is an explicit user/API intent:

```text
manual start
    ↓
manual intent ACTIVE

manual stop
    ↓
manual intent COMPLETED
```

Manual start never creates a second recorder if formal recording is already active.

Manual stop means:

> stop the manual reason for recording

not:

> force-stop the camera recorder regardless of all other policies.

Examples:

### Manual inside continuous

```text
continuous  ─────────────────────────────
manual            ─────────

media       ─────────────────────────────
```

Stopping manual changes no physical recording state.

### Manual extends an event recording

```text
event       ──────── post-roll
manual             ──────────────────

media       ──────────────────────────
```

When event/post-roll ends, manual keeps the same RecordingSession alive.

### Manual starts while idle

A new RecordingSession begins at manual start time.

Manual recording does not automatically consume event pre-roll unless a future explicit manual-pre-roll setting is introduced.

## Hybrid policy

Initial V2 meaning of:

```text
mode = hybrid
```

is:

> scheduled baseline recording + event-triggered recording outside scheduled windows.

Behavior:

```text
inside configured schedule
    → schedule intent keeps recording active
    → events annotate/add retention only

outside schedule
    → idle prebuffer
    → event can create event intent with pre/post-roll
```

This gives a useful hybrid model without running continuous recording 24/7.

Example:

```text
schedule 08:00-18:00

07:15 person event
  → event recording around 07:15

08:00-18:00
  → scheduled recording continuously

12:30 motion
  → marker + event retention on existing schedule media

20:10 vehicle
  → event recording around 20:10
```

If a future product mode needs continuous 24/7 plus event annotation, that is already represented by continuous mode because events are always detected/annotated independently.

## Segment clock rule

This rule is critical:

> Active-intent changes do not reset formal segment cadence.

Example:

```text
RecordingSession starts from event pre-roll at 12:00:07
segment duration = 5m

segments:
12:00:07 ─ 12:05:07
12:05:07 ─ 12:10:07
12:10:07 ─ 12:15:07
```

If:

```text
12:03 manual starts
12:04 event ends
12:04:10 post-roll ends
12:11 schedule begins
```

and at least one intent remains active throughout, segment boundaries stay anchored to:

```text
12:00:07
12:05:07
12:10:07
12:15:07
```

There is no 12:03 or 12:11 force-cut.

A new segment clock begins only when the previous RecordingSession truly ended and a later request starts a new RecordingSession.

## Session merge / split rule

Two recording reasons belong to the same RecordingSession when there is no period in which the effective active-intent set becomes empty.

Conceptually:

```text
same session
⇔
union(active intent intervals) is continuous
```

Example:

```text
event     10:00:00 ───── 10:00:20 + post-roll to 10:00:30
manual                         10:00:25 ───── 10:05:00
```

Because manual starts before event post-roll ends, the intervals overlap and one RecordingSession continues.

But:

```text
event     ends 10:00:30
manual    starts 10:00:35
```

there is a true 5-second period with no active recording intent.

Result:

```text
RecordingSession A ends 10:00:30
IDLE_PREBUFFER 10:00:30 ─ 10:00:35
RecordingSession B begins 10:00:35
```

Do not merge across a true no-intent gap merely to make history look continuous.

## Policy changes while recording

Changing RecordingPolicy updates intents rather than force-restarting media.

Examples:

### continuous → event

If continuous mode is disabled while no event/manual/schedule intent remains:

- complete continuous intent;
- end current RecordingSession;
- return to idle prebuffer.

If an event/manual intent is still active:

- complete continuous intent;
- keep the same RecordingSession;
- continue recording under remaining intent(s).

### event → continuous

If an event RecordingSession is active and policy changes to continuous:

- activate continuous intent;
- keep the same RecordingSession;
- do not restart recorder;
- do not reset 5-minute segment clock.

### schedule edit

Editing a schedule recalculates current/future schedule intents.

Do not force-cut media merely because schedule configuration changed if another intent still requires recording.

## Retention interaction

RecordingIntent controls why media is recorded.

RetentionClaim controls how long resulting media must remain.

They are related but separate.

Examples:

```text
continuous intent
    → continuous retention claim

event overlaps existing segment
    → event retention claim

manual overlaps existing segment
    → manual retention claim
```

A RecordingSegment may therefore be created once and carry several claims.

Effective retention follows Spec 0005.

## UI behavior

The UI should not force one mutually-exclusive recording badge when several reasons are active.

Recommended state display:

```text
Recording
  reasons:
    Continuous
    Motion Event
    Manual
```

For compact views, show one recording indicator plus badges/icons for active reasons.

The manual recording button reflects only the manual intent:

```text
manual inactive → Start manual recording
manual active   → Stop manual recording
```

If continuous recording is also active, pressing "Stop manual recording" must not make the UI imply that all recording stopped.

After the manual intent ends, the UI should still show "Recording · Continuous".

## API behavior

Prefer intent-oriented control endpoints.

Conceptually:

```text
POST /cameras/{id}/recording/manual/start
POST /cameras/{id}/recording/manual/stop

GET /cameras/{id}/recording/state
```

State response may contain:

```json
{
  "media_state": "formal_recording",
  "recording_session_id": "session_01",
  "active_intents": [
    { "type": "continuous" },
    { "type": "event", "source_id": "evt_01" },
    { "type": "manual" }
  ]
}
```

External integrations still express RecordingTrigger/event intent and never manipulate the media process directly.

## Restart recovery

After zero-nvr restart:

- continuous intent is reconstructed from enabled RecordingPolicy;
- schedule intent is reconstructed from current schedule occurrence;
- active event intent is reconstructed from persisted DetectionEvent/event lifecycle where possible;
- manual intent must be persisted so an intentional manual recording can resume until explicitly stopped or administratively recovered;
- RecordingSession/media recovery follows actual segment/runtime state and records any interruption.

A runtime restart may create a physical discontinuity/partial segment, but it must not silently discard the business reasons that were still active.

## Concurrency

RecordingManager serializes/reconciles intent transitions per camera.

Required properties:

- duplicate manual start is idempotent;
- duplicate manual stop is idempotent;
- repeated schedule evaluation does not create duplicate schedule intents;
- repeated event START for the same logical DetectionEvent does not create duplicate intents;
- event post-roll cancellation and new intent arrival are race-safe;
- no two workers independently decide to start two formal recorders for the same camera.

Implementation must document the per-camera synchronization/locking strategy.

## Structured logging

Important actions include:

```text
intent_started
intent_completed
intent_cancelled
intent_joined_session
intent_left_session
recording_session_started
recording_session_continued
recording_session_completed
recording_reason_changed
```

EventLog details should make it possible to answer:

- what currently requires this camera to keep recording?
- why did recording start?
- why did it continue after one reason ended?
- why did clicking manual stop not stop the recorder?
- which intent caused the final stop?

## Invariants

1. A camera has at most one formal recording media pipeline.
2. Recording reasons are additive RecordingIntents, not mutually destructive recorder modes.
3. RecordingSession spans one uninterrupted formal-recording interval and may contain several intent types over its lifetime.
4. A RecordingSession stays active while at least one RecordingIntent requires media.
5. Adding/removing an intent while another remains active never restarts the recorder.
6. Intent changes never reset the formal segment clock.
7. Manual stop removes only the manual intent.
8. Events never restart continuous/schedule/manual recording.
9. Hybrid means scheduled baseline + event-triggered recording outside schedule in initial V2.
10. Event pre/post-roll applies to event intent; it does not rewrite other intents' lifecycles.
11. A true interval with zero active intents ends the RecordingSession.
12. RetentionClaims are separate from RecordingIntents and can coexist on one RecordingSegment.
13. Manual intent survives control-plane restart until explicitly stopped/recovered.
14. Per-camera intent transitions are serialized/idempotent to prevent duplicate recorders.
15. Non-obvious intent arbitration/state-transition/concurrency behavior requires comments per Development Guidelines.

## Transport outage interaction

RecordingIntent expresses the requirement to record, not proof that media is currently available. A camera source outage does not remove active RecordingIntents and does not end RecordingSession while at least one intent remains active. The physical RecordingSegment closes at confirmed media loss and recovery starts a new segment. See [Spec 0008 — Stream Loss, Reconnect, and Recording Recovery](0008-stream-reconnect-and-recording-recovery.md).
