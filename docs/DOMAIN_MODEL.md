# Canonical Domain Model

This document defines the initial business entities that external components must map into.

## Identity principle

A Camera represents a stable monitoring point.

Changing ONVIF credentials, replacing an RTSP URL, switching adapter implementations, or moving media runtime must not silently create a new Camera identity.

## Camera

Core fields:

```text
id
name
enabled
location
manufacturer
model
form_factor
storage_label
created_at
updated_at
```

Owns one current CameraConnection.

## CameraConnection

Represents the current control/media connection configuration.

```text
camera_id
adapter
host
credentials_ref
revision
verification_status
verified_at
config
```

Candidate adapters:

```text
manual_rtsp
onvif
hik_sdk
gb28181
```

Credentials must not be duplicated into public read models.

## MediaStream

Canonical logical stream, independent from external media-engine identifiers.

```text
id
camera_id
role            main | preview | detection | audio
codec
width
height
fps
source_uri_ref
media_plane_key
status
```

The MediaPlane maps a MediaStream to a ZLM runtime stream.

## RecordingPolicy

Describes desired recording behavior.

```text
camera_id
mode                          continuous | schedule | event | hybrid
schedule
prebuffer_enabled
idle_prebuffer_segment_seconds
formal_record_segment_seconds
pre_roll_seconds
post_roll_seconds
retention_policy_id
enabled
```

V2 recording defaults are:

```text
prebuffer_enabled               = true
idle_prebuffer_segment_seconds  = 20
formal_record_segment_seconds   = 300
pre_roll_seconds                = 10
post_roll_seconds               = 10
```

These values are persisted configuration and must be editable from Recording Settings. They are defaults rather than hard-coded runtime constants.

The 20-second segment target applies only to temporary idle tmpfs PrebufferFragments. Formal continuous/manual/schedule/event recording defaults to 5-minute RecordingSegments. For event recording, required pre-roll is included inside the first 5-minute formal segment window.

Event recording duration itself is not fixed in advance. Stateful events keep the event RecordingIntent active until the final event ends, after which post-roll is applied. Other active intents may keep the same RecordingSession alive after the event intent completes.

Initial V2 hybrid semantics are: scheduled baseline recording during configured schedule windows, plus event-triggered recording outside those windows.


## RetentionPolicy

Defines media retention and disk-pressure behavior. System defaults may be overridden per camera.

```text
id
name
continuous_keep_days
schedule_keep_days
event_keep_days
manual_keep_days
warning_usage_percent
cleanup_start_percent
critical_usage_percent
emergency_usage_percent
cleanup_target_percent
min_free_bytes
created_at
updated_at
```

Initial defaults:

```text
continuous_keep_days = 7
schedule_keep_days   = 7
event_keep_days      = 30
manual_keep_days     = 30

warning_usage_percent   = 80
cleanup_start_percent   = 85
critical_usage_percent  = 92
emergency_usage_percent = 96
cleanup_target_percent  = 80
```

See [Spec 0005 — Recording Retention, Disk Pressure, and Safe Purge](specs/0005-recording-retention-and-purge.md).

## RetentionClaim

Represents one reason a RecordingSegment must remain available.

```text
id
recording_segment_id
reason
priority
retain_until
source_type
source_id
created_at
```

Typical reasons:

```text
continuous_policy
schedule_policy
event_policy
manual_policy
user_lock
upload_source
export_job
system_recovery
```

Finite effective retention is the maximum `retain_until` across active claims. `user_lock` is indefinite until explicitly unlocked.

This claim model is required because one 5-minute physical segment may simultaneously belong to normal recording and contain one or more events with longer retention.

## RecordingIntent

Represents one business reason why a camera currently requires formal recording.

```text
id
camera_id
intent_type          continuous | schedule | event | manual
source_type
source_id
started_at
planned_end_at
ended_at
state                pending | active | post_roll | completed | cancelled
correlation_id
metadata
created_at
updated_at
```

Recording intents are additive. A camera may have continuous, event, and manual intents active at the same time without creating duplicate media recorders.

`hybrid` is a RecordingPolicy composition mode rather than a runtime intent type. Initial V2 hybrid semantics are scheduled baseline recording plus event-triggered recording outside the schedule.

See [Spec 0007 — Recording Intent Arbitration and Mode Composition](specs/0007-recording-intent-arbitration.md).

## RecordingSession

Represents one maximal uninterrupted formal-recording interval owned by zero-nvr.

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

A RecordingSession remains active while at least one RecordingIntent requires media.

`origin_intent_type` records which intent caused the idle → formal transition for diagnostics/history. It is not a mutually exclusive recording classification.

Adding or removing another intent while the active-intent set remains non-empty:

- does not restart the recorder;
- does not create a second media pipeline;
- does not reset the formal segment clock;
- does not force a physical segment boundary.

A true interval with zero active RecordingIntents ends the RecordingSession. A later intent starts a new RecordingSession.

RecorderBackend processes are runtime implementations of this session/media requirement, not the business identity of individual intents.

## PrebufferFragment

Temporary media produced only for idle event pre-recording.

```text
id
camera_id
started_at
ended_at
duration
path
state           writing | ready | protected | consumed | expired
created_at
```

Default physical target is 20 seconds.

PrebufferFragment is not a canonical historical recording. When a RecordingSession starts, the required fragment ranges become source material for the first formal RecordingSegment and may be deleted after that formal segment is verified.

## RecordingSegment

The canonical persisted formal-recording timeline unit.

```text
id
camera_id
stream_role
sequence
started_at
ended_at
duration
codec
container
size
local_object_id
integrity_status
completion_reason     normal_boundary | session_end | manual_stop | schedule_end | source_lost | runtime_restart | media_discontinuity | failure
created_at
```

Segment identity remains stable even if its media object later moves to remote storage.

For a healthy active RecordingSession, intermediate RecordingSegments follow the configured formal segment cadence anchored at `RecordingSession.started_at`. Shorter files are expected only for the final session segment or an explicit interruption/recovery boundary. `completion_reason` makes that distinction queryable.

Canonical RecordingSegment timestamps are UTC. Calendar/day boundaries do not force segment rollover. Physical location belongs to StorageObject and uses a stable object key such as:

```text
recordings/{name_id}/{YYYY-MM-DD}/{name_id}_{YYYY-MM-DD}_{HH-MM-SS}.mp4
```

The local layout uses the Camera's stable human-readable name/id, configured recording timezone, local start date, and human-readable recording start time. See [Spec 0004 — Recording Storage Layout and Time Index](specs/0004-recording-storage-layout.md).

## RecordingSessionSegment

Maps one logical RecordingSession onto the required range of one physical RecordingSegment.

```text
recording_session_id
recording_segment_id
sequence
use_started_at
use_ended_at
created_at
```

A RecordingSession may span multiple physical MP4 files. The first/last physical files may contain additional footage outside the logical session; `use_started_at` / `use_ended_at` define the business-visible range.

This mapping allows normal playback to cross segment boundaries without first generating a merged MP4. A single-file crop/concat is a derived export operation.

See [Spec 0003 — Rolling MP4 Pre-buffer and Event Segment Composition](specs/0003-rolling-mp4-prebuffer.md).

## DetectionEvent

All event providers normalize here. DetectionEvent is also the authoritative source for event timeline markers.

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
confidence
zone
snapshot_object_id
recording_session_id
correlation_id
metadata
created_at
updated_at
```

Canonical event types should include at least:

```text
motion
person
vehicle
intrusion
tamper
digital_input
face
plate
sound
custom
unknown
```

For stateful events:

```text
START → ACTIVE → END
```

While ACTIVE, `ended_at` remains NULL.

For instant events, the event is a zero-duration Marker:

```text
started_at = occurred_at
ended_at   = occurred_at
status     = completed
```

Instant events do not invent an artificial active duration. Recording policy applies the normal pre-roll/post-roll window around the occurrence timestamp.

Repeated activity for the same logical active event must not create duplicate business events or timeline markers. Provider metadata may be stored, but UI/business rules should prefer canonical fields.

Timeline seek offsets are derived from absolute event timestamps rather than stored as authoritative offsets.

## RecordingTrigger

Represents an explicit external or internal **recording intent** when an integration needs to ask zero-nvr to preserve/record something without exposing recorder-process commands.

It is not the canonical model for stateful sensor events. Motion/person/presence-style START/END input should normalize into DetectionEvent and then be evaluated by RecordingManager.

Conceptual fields:

```text
id
camera_id
source
external_id
trigger_type
received_at
processed_at
status
reason
correlation_id
metadata
created_at
```

Typical sources may include:

```text
home_assistant
mqtt
webhook
manual
api
system
```

Typical processing states may include:

```text
received
accepted
ignored
merged
rejected
failed
```

RecordingTrigger records what intent was received and how zero-nvr handled it. It never directly represents or controls an FFmpeg/ZLMediaKit process.

Stateful event-driven recording behavior is defined by DetectionEvent + RecordingSession in [Spec 0002 — Event Recording Lifecycle](specs/0002-event-recording-lifecycle.md).

## AlertRule

```text
id
name
enabled
camera_scope
event_filters
time_filters
actions
cooldown
```

## AlertDelivery

Tracks every attempted notification/action.

```text
id
alert_rule_id
detection_event_id
backend
status
attempts
last_error
delivered_at
```

## StorageTarget

```text
id
type
name
enabled
priority
config
quota
health
```

Types:

```text
local
s3
rclone
openlist
```

## StorageObject

Represents a physical copy of media/data.

```text
id
logical_kind
logical_id
storage_target_id
object_key
size
checksum
state
verified_at
created_at
```

A RecordingSegment can have multiple StorageObjects.

## UploadJob

```text
id
storage_object_id
target_id
state
attempt
next_retry_at
last_error
created_at
updated_at
```

State direction:

```text
PENDING
UPLOADING
VERIFYING
REMOTE_READY
FAILED
```

Local-purge eligibility is a policy decision after verified remote readiness.

## PlaybackSession

Tracks authorized live/historical playback when needed.

```text
id
user_id
camera_id
mode
created_at
expires_at
metadata
```


## PlaybackTimeline

A non-authoritative read model returned by playback APIs for an absolute time range.

It is composed from RecordingSegment, StorageObject, DetectionEvent, recording policy/runtime history, and retention state rather than persisted as the primary source of truth.

Conceptual shape:

```text
range_start_ms
range_end_ms

tracks[]
  camera_id

  segments[]
    recording_segment_id
    start_ms
    end_ms
    availability
    playback_ref

  gaps[]
    start_ms
    end_ms
    reason

  events[]
    detection_event_id
    event_type
    lifecycle_kind
    start_ms
    end_ms
```

Playback API timestamps are UTC Unix milliseconds.

Initial segment availability values:

```text
local
remote
cached_remote
missing
corrupted
purged
```

Initial gap reasons:

```text
not_scheduled
no_event
source_lost
runtime_restart
storage_failure
missing_media
purged
unknown
```

Playback URLs are resolved lazily from `playback_ref`; the timeline read model must not depend on a permanent storage-specific URL.

See [Spec 0006 — Historical Playback Timeline and Multi-Camera Sync](specs/0006-historical-playback-timeline.md).

## HealthSample

```text
camera_id
kind
status
latency
details
sampled_at
```

Kinds may include:

- connectivity;
- media stream;
- recorder;
- storage;
- upload;
- device protocol.


## SourceConnectivityIncident

Represents a historical infrastructure/media-source interruption independently from DetectionEvent.

```text
id
camera_id
started_at
ended_at
state
reason
last_media_at
recovered_at
retry_count
details
created_at
updated_at
```

Typical states/reasons include:

```text
degraded
reconnecting
offline
recovered

source_lost
runtime_restart
media_discontinuity
storage_failure
```

SourceConnectivityIncident can explain playback gaps and health history. It must not be modeled as a DetectionEvent.

A connectivity incident may split physical RecordingSegments while the same RecordingSession continues if one or more RecordingIntents remain active.

See [Spec 0008 — Stream Loss, Reconnect, and Recording Recovery](specs/0008-stream-reconnect-and-recording-recovery.md).

## EventLog

Persists structured business/runtime events needed to explain recording behavior.

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

EventLog complements normal application logs. It should make recording decisions queryable from the product UI/API.

## AuditEvent

Tracks administrative/business changes.

```text
actor
action
resource_type
resource_id
before
after
created_at
```

## Invariants

1. Camera is the stable identity.
2. External component IDs are never primary business identities.
3. Recording metadata survives storage movement.
4. DetectionEvent is provider-neutral and is the source of truth for event timeline markers.
5. zero-nvr alone owns recording lifecycle decisions; event/integration providers never directly control media recorder processes.
6. Stateful event recording duration is determined by event START/END plus pre-roll/post-roll, not a fixed record duration.
7. Multiple events may share one RecordingSession while remaining independent DetectionEvents and EventLog records.
8. External explicit recording intent may enter through RecordingTrigger, but stateful sensor events normalize into DetectionEvent.
9. Credentials do not appear in public read contracts.
10. Media runtime state is reconstructable and not authoritative metadata.
11. Remote upload requires verification before local purge eligibility.
12. Historical data blocks destructive Camera deletion unless an explicit archival/deletion design says otherwise.
13. Instant events are zero-duration DetectionEvents; they use recording pre-roll/post-roll without a fabricated event lifetime.
14. RecordingSession logical boundaries are independent from physical MP4 segment boundaries.
15. RecordingSessionSegment defines which time range of each physical segment contributes to a logical recording.
16. Event pre-buffer segment rollover must never require recorder stop/start to preserve correctness.
17. Idle tmpfs pre-buffering and formal recording are mutually exclusive modes of one recording pipeline, not duplicate recorders.
18. Idle 20-second tmpfs files are temporary PrebufferFragments, not canonical RecordingSegments.
19. The first event RecordingSegment window starts at RecordingSession.started_at, including pre-roll; a pre-buffer fragment boundary must not restart the 5-minute formal segment clock.
20. The first formal RecordingSegment may be assembled from one or more protected PrebufferFragment ranges plus persistent continuation media.
21. While a formal RecordingSession remains active and healthy, all intermediate RecordingSegments follow the configured duration from the session-anchored segment clock.
22. A normal RecordingSession completion may produce a shorter final segment; abnormal interruptions may also produce partial segments and must be identified by `completion_reason`.
23. The tail of a completed formal recording remains eligible to bridge pre-buffer warm-up for at least the configured pre-roll interval.
24. Recording segment durations and pre/post-roll values are policy/configuration data exposed through Recording Settings, not hard-coded constants.
25. Segment-duration configuration changes apply at a safe next segment boundary without force-cutting the current MP4 merely to apply the setting.
26. Canonical recording timestamps are UTC; all local directory/file timestamps are generated in the effective configured recording timezone so they align with camera wall-clock/OSD time.
27. Midnight/date boundaries never force a formal segment split.
28. Camera.storage_label is a stable human-readable storage identity; changing Camera display name does not silently rename historical media.
29. Local recording paths must remain browseable without zero-nvr by camera/date/start time.
30. Recording paths/object keys are storage metadata; playback and retention still use database timestamps/relations rather than directory scanning.
31. Retention is claim-based; a shared physical segment keeps the strongest active retention requirement without duplicating media.
32. User-locked media is never automatically purged.
33. Upload success without verified REMOTE_READY state never permits safe local-source deletion.
34. Critical disk-pressure purge is priority ordered and explicitly logged; currently writing/finalizing media is never an automatic purge candidate.
35. Historical playback is absolute-time driven; physical MP4 boundaries and filenames are never the playback clock.
36. Playback API time values use UTC Unix milliseconds consistently.
37. PlaybackTimeline is a derived read model with playable segments, explicit gaps, and DetectionEvent markers.
38. Multi-camera historical playback shares one Master Clock; one camera's gap never shifts another camera to a different absolute time.
39. Playback references resolve storage lazily so local/remote migration does not rewrite timeline semantics.
40. Purged, missing, corrupted, source-loss, and intentionally-unrecorded ranges remain distinguishable in playback.
41. Recording reasons are additive RecordingIntents; a camera has at most one formal media pipeline.
42. RecordingSession spans one uninterrupted formal-recording interval and may contain several overlapping intent types.
43. Adding/removing an intent while another remains active never restarts the recorder or resets formal segment cadence.
44. Manual stop removes only the manual intent and never force-stops other active recording reasons.
45. Initial V2 hybrid mode means scheduled baseline recording plus event-triggered recording outside schedule windows.
46. Confirmed source/media loss closes the current physical RecordingSegment but does not end RecordingSession while any RecordingIntent remains active.
47. Post-reconnect media always starts a new RecordingSegment and is never appended into an interrupted MP4.
48. A real media discontinuity resets the physical formal-segment cadence from actual recovery time.
49. Infrastructure/source-connectivity incidents are distinct from DetectionEvent and may explain historical playback gaps.
50. Camera offline/reconnecting state does not cancel enabled RecordingIntents or background source retry by itself.
