# Spec 0002 — Event Recording Lifecycle

Status: **accepted**

## Goal

Define how zero-nvr turns canonical events into recording behavior without allowing event providers or integrations to control recorder processes directly.

This specification covers both **stateful events** such as motion/person presence and **instant events** such as doorbell presses, line crossing, one-shot AI detections, and Webhook alarms.

## Core ownership rule

> Event sources report what happened. zero-nvr decides what to record.

Only zero-nvr's RecordingManager owns recording lifecycle decisions.

External and internal producers may report events through ONVIF, vendor adapters, local RTSP detection, Home Assistant, MQTT, Webhook, AI providers, or other adapters. They must not directly start/stop FFmpeg or manipulate ZLMediaKit runtime objects.

The canonical flow is:

```text
Event source
   ↓
DetectionEvent START / END
   ↓
RecordingManager
   ├── create/extend/keep RecordingSession
   ├── attach event timeline marker
   └── write EventLog
   ↓
RecorderBackend / existing recording runtime
```

## Stateful event model

A stateful event has a lifecycle:

```text
START → ACTIVE → END
```

Examples:

```text
person present    ON  → START
person present    OFF → END

motion active     ON  → START
motion active     OFF → END
```

While ACTIVE, `ended_at` remains NULL.

Repeated START/ON notifications for the same logical active event do not create duplicate business events. Repeated activity may refresh provider/runtime metadata, but the timeline keeps one logical event.

An END/OFF received when no matching active event exists is ignored as a state transition and may be recorded as a debug/warning log.

## Instant event model

An instant event has one authoritative occurrence timestamp and no artificial active duration.

Examples include:

```text
doorbell_pressed
line_crossing
one-shot AI detection
face recognized
plate recognized
Webhook alarm
```

An instant event is represented as a zero-duration logical event:

```text
started_at = occurred_at
ended_at   = occurred_at
status     = completed
```

The event itself remains a single timeline Marker at `occurred_at`. zero-nvr must not invent a fake 5s/10s event lifetime merely to control recording.

With the default V2 event-recording policy:

```text
pre_roll  = 10 seconds
post_roll = 10 seconds
```

an isolated instant event at time `t` produces the desired recording window:

```text
recording_start = t - 10s
planned_end_at  = t + 10s
```

If an event RecordingSession is already active, the instant event does not restart the recorder. It creates its own DetectionEvent/Marker/EventLog and extends the pending stop boundary only when required:

```text
planned_end_at = max(current_planned_end_at, t + post_roll)
```

If one or more stateful events are ACTIVE, they continue to keep the RecordingSession alive. The instant event is still recorded as an independent Marker and EventLog entry; its 10-second post window must be respected when the session later becomes eligible to stop.

Repeated instant events remain separate business events unless a provider-specific deduplication rule explicitly identifies them as the same source event (for example, the same stable `external_id`).

## Event recording window

Default V2 event-recording policy:

```text
pre_roll  = 10 seconds
post_roll = 10 seconds
```

These are recording-policy settings, not detector settings.

### First event when no recording exists

When the first stateful event becomes ACTIVE and no recording is active:

```text
recording_start = event.started_at - pre_roll
```

The pre-roll portion is supplied from the maintained recording/media buffer.

The RecordingSession then remains open while any event is ACTIVE.

### Active events keep recording alive

For each camera, RecordingManager conceptually maintains:

```text
active_events
```

Rule:

```text
active_events != empty
→ event recording must remain active
```

There is no fixed `motion_record_duration` or equivalent event-recording duration.

### Last event END starts post-roll

When an event ends:

1. set `ended_at`;
2. remove it from the camera's active event set;
3. if other events remain ACTIVE, keep recording with no stop countdown;
4. if no active events remain, schedule stop at:

```text
planned_end_at = last_event_end + post_roll
```

### New event during post-roll

If a new event START arrives before `planned_end_at`:

- cancel the pending stop;
- keep the same RecordingSession;
- do not restart the recorder;
- create a new independent DetectionEvent/timeline marker;
- after all events become inactive again, recalculate a fresh post-roll window.

Example:

```text
person   12:00:20 ───── 12:00:35
motion                         12:00:41 ───── 12:00:55

record   12:00:10 ─────────────────────────── 12:01:05
          pre-roll                          post-roll
```

The second event arrives inside the first event's post-roll, so the session continues and the final post-roll is calculated from 12:00:55.

## Multiple simultaneous events

Multiple events do not repeatedly trigger recorder start operations.

Each event remains independently addressable:

```text
RecordingSession
├── DetectionEvent: motion
├── DetectionEvent: person
└── DetectionEvent: vehicle
```

Each event produces its own:

- canonical event record;
- timeline marker;
- event/business log entries;
- source/type metadata.

They may all share one RecordingSession.

The resulting recording duration is determined by the union of active event lifetimes plus pre-roll/post-roll, not by a fixed per-event duration.

## Events during non-event recording

When the camera is already being recorded by another recording mode such as:

```text
continuous
manual
schedule
```

an incoming event:

- does not restart recording;
- does not change that recording mode's lifecycle;
- creates/updates the canonical DetectionEvent;
- creates the timeline marker;
- writes EventLog entries;
- links the event to the relevant recording timeline/session where applicable.

## Timeline markers

DetectionEvent is the source of truth for event markers.

Markers must be derived from absolute event timestamps:

```text
started_at
ended_at
```

Do not store only a playback offset as the authoritative value.

Playback seek offsets are derived when needed:

```text
seek_offset = event.started_at - recording.started_at
```

This remains valid when recordings are segmented, moved, re-indexed, or resolved from another storage backend.

## Local RTSP motion detection

RTSP itself does not provide motion START/END semantics. The built-in local motion detector must derive them from video analysis.

The detector layer owns motion-state inference. RecordingManager only receives canonical START/END events.

### Detector state machine

Conceptual state machine:

```text
IDLE
  │ sustained motion above start condition
  ▼
ACTIVE
  │ sustained quiet below end condition
  ▼
IDLE
```

The detector should use hysteresis instead of a single threshold:

```text
motion_start_threshold
motion_end_threshold
```

with:

```text
motion_start_threshold > motion_end_threshold
```

The intermediate range preserves the current state, preventing rapid ON/OFF oscillation around one threshold.

The detector also owns confirmation/hold timing:

```text
motion_start_hold
motion_end_hold
```

Typical semantics:

- `motion_start_hold`: short confirmation before START;
- `motion_end_hold`: sustained quiet required before END.

Exact default threshold/hold values remain implementation tuning parameters.

### No fixed motion recording duration

V2 must not use a detector setting equivalent to:

```text
motion_record_duration = N seconds
```

to determine event recording length.

Instead:

```text
detector decides Motion START / END
RecordingManager applies pre_roll / active lifetime / post_roll
```

This keeps detector semantics and recording policy separate.

### Pulse-only event sources

Some sources may emit repeated motion pulses without an explicit OFF.

Such an adapter/detector may use an internal hold timeout to infer the end of one logical event:

```text
pulse → refresh hold deadline
pulse → refresh hold deadline
no pulse until deadline → Event END
```

The pulse hold timeout belongs to event normalization/detection, not to recording duration.

Repeated pulses belonging to the same logical event must not create repeated timeline markers.

## RecordingSession

RecordingSession represents one actual recording lifecycle owned by zero-nvr.

Conceptual fields:

```text
id
camera_id
recording_type      event | continuous | manual | schedule
started_at
planned_end_at
ended_at
status
created_at
updated_at
```

For an active event recording, `planned_end_at` may be NULL while one or more events remain ACTIVE.

When the final active event ends, `planned_end_at` becomes the current post-roll deadline. A new event before that deadline clears/replaces that pending stop decision.

## DetectionEvent additions

Event handling requires canonical fields equivalent to:

```text
id
camera_id
source_kind
provider
external_id
event_type
lifecycle_kind      stateful | instant
status              active | completed
started_at
ended_at
recording_session_id
correlation_id
metadata
created_at
updated_at
```

Provider-specific payloads may be retained in metadata, but business logic must use canonical fields.

## EventLog

Operational text logs are not sufficient to explain NVR behavior. zero-nvr should also persist/query structured business event logs.

Conceptual EventLog fields:

```text
id
timestamp
level
category
event_type
camera_id
detection_event_id
recording_session_id
correlation_id
action
reason
details
```

Important actions include:

```text
event_started
event_ended
recording_started
post_roll_started
post_roll_cancelled
recording_extended
marker_created
recording_completed
event_ignored
event_rejected
```

The log should make it possible to answer:

- why did this recording start?
- why did it continue for this long?
- which events occurred inside it?
- why was a stop cancelled or delayed?

## Correlation

A `correlation_id` should follow a logical event/recording flow across:

```text
ingress / adapter
DetectionEvent
RecordingManager
RecordingSession
RecorderBackend
media/file finalization
EventLog
```

This is especially important once FastAPI, workers, ZLMediaKit callbacks, MQTT/HA adapters, and asynchronous jobs are involved.

## Invariants

1. zero-nvr is the only owner of recording lifecycle decisions.
2. Event providers never directly control FFmpeg/ZLMediaKit recording processes.
3. Stateful event recording duration is not fixed in advance.
4. Any ACTIVE event keeps an event RecordingSession alive.
5. Post-roll starts only after the final active event ends.
6. A new event during post-roll cancels the pending stop and reuses the same RecordingSession.
7. Multiple events remain independent business events even when they share one recording.
8. Every event remains independently visible as a timeline marker and in EventLog.
9. Existing continuous/manual/schedule recording is annotated by events rather than restarted.
10. RTSP motion detection owns motion-state inference; RecordingManager owns recording policy.
11. Detector hold/threshold settings and recording pre/post-roll settings are separate concerns.
12. Absolute event timestamps are authoritative; playback offsets are derived.
13. Instant events are zero-duration markers and use the normal pre-roll/post-roll policy without an invented event hold duration.
14. An isolated instant event uses the default 10s pre-roll + 10s post-roll window; later events may extend the same RecordingSession.
15. Recording/event state-machine implementations must include complete comments explaining non-obvious timing, cancellation, merge, and edge-case behavior, following [Development Guidelines](../DEVELOPMENT_GUIDELINES.md).
