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

The 20-second segment target applies only to idle tmpfs pre-buffering. Formal continuous/manual/schedule/event recording defaults to 5-minute physical segments.

Event recording duration itself is not fixed in advance. Stateful events keep the recording active until the final event ends, after which post-roll is applied.

## RecordingSession

Represents one actual recording lifecycle owned by zero-nvr.

```text
id
camera_id
recording_type      event | continuous | manual | schedule
started_at           logical/business start
planned_end_at
ended_at             logical/business end
actual_media_started_at
actual_media_ended_at
status
created_at
updated_at
```

For event recording:

- `planned_end_at` may be NULL while any event remains ACTIVE;
- the final event END sets `planned_end_at = ended_at + post_roll`;
- a new event before `planned_end_at` cancels/replaces the pending stop decision;
- multiple events may share one RecordingSession without repeatedly starting the recorder.

RecorderBackend processes are runtime implementations of the session intent, not the business identity of the recording.

## RecordingSegment

The canonical timeline unit.

```text
id
camera_id
stream_role
started_at
ended_at
duration
codec
container
size
local_object_id
integrity_status
created_at
```

Segment identity remains stable even if its media object later moves to remote storage.

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
17. tmpfs event pre-buffering is active only when the camera has no formal RecordingSession.
18. Active continuous/manual/schedule/event recording media is reused for event timeline/pre-roll coverage instead of duplicated into tmpfs.
19. The tail of a completed formal recording remains eligible to bridge pre-buffer warm-up for at least the configured pre-roll interval.
20. Recording segment durations and pre/post-roll values are policy/configuration data exposed through Recording Settings, not hard-coded constants.
21. The default formal recording segment target is 300 seconds; changes apply at a safe next segment boundary without force-cutting the current MP4.
