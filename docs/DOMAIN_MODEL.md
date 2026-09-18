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
mode            continuous | schedule | event | hybrid
schedule
segment_target
pre_roll
post_roll
retention_policy_id
enabled
```

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

## DetectionEvent

All event providers normalize here.

```text
id
camera_id
source_kind
provider
event_type
started_at
ended_at
confidence
zone
snapshot_object_id
recording_id
metadata
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

Provider metadata may be stored, but UI/business rules should prefer canonical fields.

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
4. DetectionEvent is provider-neutral.
5. Credentials do not appear in public read contracts.
6. Media runtime state is reconstructable and not authoritative metadata.
7. Remote upload requires verification before local purge eligibility.
8. Historical data blocks destructive Camera deletion unless an explicit archival/deletion design says otherwise.
