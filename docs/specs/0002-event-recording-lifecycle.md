# Spec 0002 — Event Recording Lifecycle and RecordingTrigger

Status: **accepted**

## Goal

Define how canonical Events request recording behavior without allowing event providers/integrations to directly control ZLMediaKit or create duplicate video.

Core rule:

> Event providers report observations. zero-nvr evaluates product policy and creates/updates RecordingTrigger. Recording arbitration decides whether the single ZLM recorder must be active.

## Event source boundary

Possible event sources include:

- ONVIF;
- optional vendor adapter;
- Frigate;
- Home Assistant;
- MQTT;
- Webhook/API;
- zero-nvr manual/system source.

For the V1 blocking execution path, RecordingTrigger lifecycle entry points are
ONVIF and explicit authorized API/manual requests. Frigate/AI and Home
Assistant trigger entry points remain V1.1/non-blocking unless explicitly
re-prioritized. All provider adapters reuse the same RecordingTrigger service
contract rather than owning recorder state.

No source is allowed to directly:

- call ZLM recorder APIs as recording authority;
- start its own permanent FFmpeg recorder;
- delete/purge recordings;
- bypass retention/protection policy.

## Event

Event is the canonical record of what occurred.

Typical fields include:

```text
source
source_event_id
camera_id
category
label
started_at
ended_at
confidence
zone
severity
snapshot_ref
metadata
```

Provider new/update/end messages for the same source event UPSERT one Event.

## RecordingTrigger

RecordingTrigger is the canonical request/evidence that an Event or external action requires recording behavior.

Minimum fields:

```text
id
camera_id
type
source
source_event_id
requested_at
pre_roll_seconds
post_roll_seconds
planned_start_at
planned_end_at
state
reason
correlation_id
metadata
created_at
updated_at
```

Types may include:

```text
MOTION
AI_OBJECT
ONVIF_EVENT
VENDOR_EVENT
HOME_ASSISTANT
API
MANUAL_EVENT
```

## Policy evaluation

Not every Event must trigger EVENT_ONLY recording.

Recording policy may consider NVR-relevant fields such as:

- camera;
- event category/type;
- label;
- zone;
- confidence;
- duration;
- time/day window;
- enabled state.

If policy matches:

```text
Event
-> RecordingTrigger
-> RecordingIntent arbitration
-> one ZLM recorder
```

Do not build a general expression/automation engine.

## Stateful event lifecycle

For providers that expose a stateful tracked event:

```text
new/start
-> Event ACTIVE
-> create/update trigger
-> provider update refreshes Event/trigger deadline as needed
-> provider end
-> Event completed
-> planned_end = ended_at + post_roll
```

The provider owns motion/object state inference.

zero-nvr does not invent a second detector state machine on top of Frigate/ONVIF/vendor events.

## Instant/pulse event

An instantaneous event can still request an interval:

```text
planned_start = event_time - pre_roll
planned_end   = event_time + post_roll
```

The physical pre-roll mechanism may not be able to provide the entire requested past interval. Coverage is reported honestly.

## Multiple events

Events remain independent even when their recording windows overlap.

Example:

```text
person Event A   20:00:10
vehicle Event B  20:00:17
```

Both Events and both RecordingTriggers remain queryable.

Recording arbitration takes the union of required windows and keeps one recorder active through the latest required deadline.

No duplicate event MP4 is created.

## Event during existing recording

If CONTINUOUS, SCHEDULE, or MANUAL already keeps the camera recording:

- Event is persisted;
- Event marker is placed on timeline;
- RecordingTrigger may be created for protection/semantics;
- recorder does not restart;
- no second copy of the video is generated.

Playback resolves Event time against the existing RecordingSegments.

## Pre-roll and post-roll

Default product target may be approximately:

```text
pre_roll  = 10s
post_roll = 10s
```

These are configurable policy values, not hard-coded constants.

The product semantics are frozen; the physical pre-roll implementation is not.

The design-freeze POC must validate a mature ZLM-native mechanism such as rolling HLS/fMP4/GOP capability.

zero-nvr must not implement its own compressed-video packet ring buffer.

## Event/provider loss

If a stateful provider goes offline before emitting an end:

- do not leave the Event active forever;
- provider adapter/liveness handling may finish it with an explicit reason such as provider_lost;
- post-roll semantics apply from the chosen completion time;
- provider failure does not stop continuous recording.

## Source video outage

An Event may arrive while the camera video source is unavailable.

zero-nvr still:

- persists Event;
- persists RecordingTrigger when policy matches;
- does not fabricate missing video/pre-roll;
- exposes the real timeline gap;
- reconciles desired recording when media returns.

## Protection

An AlertPolicy/event policy may create RecordingProtection over the relevant wall-clock range.

Protection is metadata/policy.

Do not copy the same event video into another "protected" folder merely to lock it.

## Export

An Event detail view may offer Export.

Export is an explicit derived-media job:

```text
Event time range
-> PlaybackResolver
-> existing RecordingSegments
-> FFmpeg clip/remux/transcode
-> Export asset
```

Export does not change recording authority.

## Correlation ID

`correlation_id` connects related evidence across:

- Event;
- RecordingTrigger;
- Alert;
- Notification;
- Export/protection actions where useful;
- Audit/system logs.

It is diagnostic/product linkage, not an authorization token.

## Acceptance tests

1. Frigate new/update/end:
   - one Event is UPSERTed;
   - one trigger lifecycle is maintained.

2. ONVIF instant motion:
   - trigger requests configured pre/post interval.

3. Two overlapping events:
   - Events stay separate;
   - one ZLM recorder remains;
   - recording end extends correctly.

4. Event during continuous recording:
   - no recorder restart;
   - no duplicate event MP4.

5. Provider disconnect:
   - unresolved state does not remain active forever;
   - recording core remains unaffected.

6. Source video unavailable:
   - Event/Trigger persist;
   - missing footage remains an explicit gap.

7. Protection:
   - retention skips protected range without copying media to a second folder.

8. Export:
   - generated only on explicit user action.

## Invariants

1. Providers do not directly own recording lifecycle.
2. Event and RecordingTrigger are distinct product concepts.
3. One source event identity is idempotently updated rather than duplicated.
4. Multiple events may extend one recording interval without duplicate recorders.
5. Existing continuous/scheduled/manual footage is annotated, not duplicated.
6. Pre-roll product semantics are separate from the POC-gated physical implementation.
7. Missing media is never fabricated.
8. `correlation_id` provides cross-workflow traceability.
