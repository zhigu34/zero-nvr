# Spec 0001 — zero-nvr Platform Architecture

Status: **initial baseline**

## Goal

Build a dedicated, extensible NVR management platform by combining mature media/protocol/infrastructure components behind a zero-nvr-owned control plane.

The platform must support, over time:

- camera onboarding and lifecycle;
- reliable live media;
- continuous/event recording;
- device-native and AI events;
- alerting;
- local/remote storage;
- upload verification;
- historical playback;
- health and operations.

## Product ownership

zero-nvr is authoritative for:

- Camera identity;
- Connection intent;
- Recording intent;
- Recording metadata;
- DetectionEvent;
- AlertRule;
- Storage state;
- Playback timeline;
- authorization and audit.

External systems must not become alternate business databases.

## Component strategy

### Reuse

Use mature components for commodity capabilities:

```text
Media server       → ZLMediaKit
Media tooling      → FFmpeg / ffprobe
ONVIF protocol     → maintained ONVIF client library
HIK private stack  → vendor SDK bridge
GB28181            → optional WVP + ZLM
Generic notices    → Apprise
Cloud transfer     → S3 / rclone / OpenList adapters
External AI        → optional Frigate/provider adapter
Home Assistant     → optional IntegrationAdapter
MQTT               → optional deep-integration transport
TURN               → optional coturn
```

### Build

zero-nvr builds:

```text
Camera domain
Adapter contracts
Recording policies
Recording index/timeline
Event normalization
Alert rules
Storage lifecycle
Upload state machine
Playback resolver
Health model
ACL/audit
Product UI
```

## Architectural requirements

### R1 — Stable Camera identity

A Camera must remain stable when:

- credentials change;
- stream URL changes;
- ONVIF profile changes;
- adapter implementation changes;
- ZLM restarts;
- recorder restarts.

### R2 — External runtime is reconstructable

ZLM stream state, FFmpeg process state and AI-provider runtime state are reconstructable from zero-nvr intent.

They must not be the only place where product configuration lives.

### R3 — One media ingress, multiple consumers

Where practical:

```text
Camera
  ↓
ZLM
  ├── Browser
  ├── Recorder
  └── Detection provider
```

Avoid independent main-stream pulls per feature.

### R4 — Provider-neutral events

Every source maps to DetectionEvent.

No alert, storage or playback policy should depend directly on vendor event payloads.

### R5 — Recording and storage are separate concerns

RecordingSegment describes the timeline/media unit.

StorageObject describes where a physical copy exists.

Moving/uploading a file must not rewrite historical recording identity.

### R6 — Remote verification before purge

A local recording becomes purge-eligible only after remote storage is verifiably readable according to the backend's capabilities.

### R7 — Optional integrations fail independently

Failure of optional components must degrade only their own capability.

Examples:

- AI provider down does not stop continuous recording;
- notification backend down does not erase events;
- cloud storage down does not stop local recording;
- HIK bridge down affects only HIK-dependent cameras.
- Home Assistant unavailable affects only HA-triggered automation.
- MQTT unavailable affects only MQTT-backed integrations.

### R9 — Stateful event recording is lifecycle-driven

Stateful event recording must be driven by canonical event START/END state, not by a fixed recording duration.

RecordingManager is the sole owner of recording lifecycle decisions:

```text
first event START
  → pre-roll + event RecordingSession

any ACTIVE event
  → keep session alive

final event END
  → begin post-roll

new event during post-roll
  → cancel pending stop and continue same session
```

Local RTSP motion detection must infer Motion START/END using detector-level threshold/hold state. Detection timing and recording pre/post-roll are separate concerns.

The accepted behavior is defined in [Spec 0002 — Event Recording Lifecycle](0002-event-recording-lifecycle.md).

### R8 — Optional integrations are load-on-demand

The default core deployment must not require:

- Home Assistant;
- MQTT broker;
- Frigate;
- OpenList;
- HIK bridge;
- WVP;
- coturn.

An integration becomes active only when explicitly enabled/configured.

For Home Assistant, the preferred progression is:

```text
REST external trigger
  ↓
optional MQTT deep integration
  ↓
optional Home Assistant Custom Integration
```

HA-triggered recording must enter the canonical RecordingTrigger/RecordingPolicy path. It must not directly start/stop FFmpeg or manipulate ZLMediaKit runtime objects.

## Initial service model

```text
zero-nvr-web
zero-nvr-api
zero-nvr-runtime
zero-nvr-worker
postgres
zlmediakit
```

These roles may initially be combined operationally if doing so does not collapse the architecture boundaries.

## Initial API domains

The exact routes are deferred, but API ownership is expected to group around:

```text
/cameras
/media
/recordings
/events
/alerts
/storage
/playback
/health
/integrations
/system
```

## Initial persistence domains

Expected PostgreSQL schema areas:

```text
Camera
CameraConnection
MediaStream
RecordingPolicy
RecordingSegment
DetectionEvent
RecordingTrigger
AlertRule
AlertDelivery
StorageTarget
StorageObject
UploadJob
PlaybackSession
HealthSample
AuditEvent
```

## First vertical slice

The first useful end-to-end slice is intentionally narrow:

```text
Create Manual RTSP Camera
       ↓
MediaPlane.ensure_stream
       ↓
ZLMediaKit
       ↓
Live session
       ↓
Browser playback
```

Then extend the same stream into:

```text
ZLM internal RTSP
       ↓
FFmpeg Recorder
       ↓
RecordingSegment
       ↓
Timeline
```

This proves the central V2 boundary before ONVIF, AI or cloud storage increases complexity.

## Acceptance for architecture baseline

The architecture is considered successfully established when:

- the control plane contains no media-server implementation;
- media runtime is hidden behind MediaPlane;
- Camera domain has no ZLM-specific primary identity;
- recorder consumes a MediaStream rather than raw Camera implementation details;
- protocol-specific device code is behind DeviceAdapter;
- events are provider-neutral;
- storage movement does not change RecordingSegment identity.
