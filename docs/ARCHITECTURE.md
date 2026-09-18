# zero-nvr Architecture Baseline

Status: **V2 initial baseline**

This document defines the architecture direction. Detailed component choices may evolve, but the ownership boundaries should remain stable.

## 1. Product definition

zero-nvr is a custom NVR platform assembled from mature protocol/media/infrastructure components around a self-owned NVR control plane.

zero-nvr owns:

- camera identity and connection lifecycle;
- recording policy and recording metadata;
- event normalization;
- alert rules and deliveries;
- storage policy and object lifecycle;
- upload orchestration;
- playback timeline;
- permissions, audit and system health.

zero-nvr does not aim to own generic protocol implementations when a mature component already exists.

## 2. Architectural principle

> Build the control plane, reuse the protocols.

External components are replaceable adapters. They are not authoritative business databases.

## 3. Logical planes

```text
┌─────────────────────────────────────────────┐
│                 Vue 3 UI                    │
│ Device / Live / Timeline / Event / Storage  │
└─────────────────────┬───────────────────────┘
                      │
                HTTP / WebSocket
                      │
┌─────────────────────▼───────────────────────┐
│            FastAPI Control Plane            │
│                                             │
│ Camera  Recording  Event  Alert  Storage    │
│ Playback  Health  ACL  Audit  Integration   │
└──────┬──────────┬──────────┬──────────┬─────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
 Device Plane  Media Plane Event Plane Job Plane
       │          │          │          │
 ONVIF lib      ZLM        Native      Worker
 HIK bridge     FFmpeg     AI          Upload
 WVP optional   coturn     External    Export
       │          │          │          Notify
       └──────────┴──────────┴──────────┘
                         │
                 Integration Plane
                 HA / MQTT / Webhook
                         │
                      Cameras

              PostgreSQL = metadata truth
                         │
          Local / S3 / rclone / OpenList
```

## 4. Source-of-truth rules

### PostgreSQL

PostgreSQL is the authoritative metadata store for:

- cameras and connections;
- stream mappings;
- recording policies;
- recording segments;
- detection events;
- alert rules and deliveries;
- storage targets and objects;
- upload jobs;
- health samples;
- audit records.

### ZLMediaKit

ZLMediaKit owns transient media runtime state only:

- active streams;
- readers;
- protocol conversions;
- live delivery;
- media-session statistics.

A ZLM stream disappearing must not delete Camera or Recording metadata.

### External AI / protocol systems

Frigate, WVP, vendor SDKs and similar systems may report capabilities/events, but zero-nvr normalizes and persists only the canonical information it needs.

## 5. Core adapter contracts

The control plane should depend on interfaces rather than implementations.

### DeviceAdapter

Responsible for device-level capabilities.

Conceptual operations:

```text
discover()
probe()
device_info()
media_profiles()
event_capabilities()
ptz_capabilities()
```

Implementations may include:

- OnvifDeviceAdapter
- HikDeviceAdapter
- Gb28181DeviceAdapter

### MediaPlane

Responsible for runtime media availability and live delivery.

```text
ensure_stream()
remove_stream()
stream_status()
play_urls()
snapshot()
health()
```

Default implementation:

```text
ZlmMediaPlane
```

### RecorderBackend

Responsible for producing recording media files/segments.

```text
start()
stop()
status()
recover()
```

Initial implementation:

```text
FfmpegRecorderBackend
```

A future ZLM recorder can be evaluated behind the same contract.

### DetectionProvider

```text
capabilities()
enable()
disable()
status()
```

Possible implementations:

- camera-native ONVIF events;
- vendor-native events;
- local lightweight detection;
- Frigate integration.

All provider outputs normalize into DetectionEvent.

### StorageBackend

```text
put()
stat()
verify()
open()
delete()
```

Possible implementations:

- LocalStorage
- S3Storage
- RcloneStorage
- OpenListStorage

### NotificationBackend

```text
send()
health()
```

Apprise-backed delivery is the preferred generic integration path.

### IntegrationAdapter

Optional external automation/integration features live behind an explicit integration boundary.

Conceptual operations:

```text
capabilities()
enable()
disable()
status()
handle_external_event()
publish_state()
```

Initial optional implementations may include:

- HomeAssistantAdapter
- MqttIntegrationAdapter
- WebhookIntegrationAdapter

Integration adapters are not required for core recording, playback, storage or device management.

## 6. Core data flows

### Live view

```text
Camera
  ↓
ZLMediaKit
  ↓
WebRTC / fMP4 / HLS
  ↓
Browser

FastAPI issues authorization/session metadata.
```

### Continuous recording

Initial V2:

```text
Camera
  ↓
ZLMediaKit
  ↓
internal RTSP
  ↓
FFmpeg Recorder
  ↓
Recording Segments
  ↓
Recording metadata
```

This intentionally separates the camera connection from the recorder process.

### Native / AI / external automation events

```text
Camera ONVIF/HIK
      or
Optional AI provider
      or
Optional IntegrationAdapter
(Home Assistant / MQTT / Webhook)
      ↓
DetectionEvent / RecordingTrigger
      ↓
Recording Policy / AlertRule
      ↓
Recording Promotion / Notification / Webhook
```

Home Assistant and similar systems must not directly start/stop FFmpeg or manipulate ZLMediaKit internals. They express external intent through canonical events/triggers; zero-nvr owns recording execution and lifecycle.

### Cloud upload

```text
RecordingObject
     ↓
UploadJob
     ↓
StorageBackend
     ↓
VERIFYING
     ↓
REMOTE_READY
     ↓
LOCAL_PURGE_ELIGIBLE
```

Local files must never be purged merely because an upload command returned success.

### Historical playback

```text
Timeline Query
     ↓
RecordingSegments
     ↓
Playback Resolver
     ├── Local
     ├── Cached Remote
     └── Remote signed/proxied
     ↓
Browser
```

## 7. Runtime roles

The initial service split is conceptual and may initially share processes where operationally simpler.

```text
zero-nvr-api
zero-nvr-web
zero-nvr-runtime
zero-nvr-worker
postgres
zlmediakit
```

Optional:

```text
hik-bridge
frigate
mosquitto
home-assistant integration
openlist
coturn
wvp
```

Optional means load-on-demand: the core zero-nvr deployment must not require the integration's process, broker, credentials or configuration to boot and record normally.

## 8. Deployment target

First supported target:

- Linux;
- Docker / Docker Compose;
- single host;
- local recording volume;
- optional remote storage.

The domain model should not assume all services remain on one host forever.

## 9. V1 migration philosophy

V1 is a reference implementation, not a code dependency.

Reuse:

- product behavior that proved useful;
- UI workflow lessons;
- failure cases;
- acceptance tests;
- data migration ideas.

Do not blindly copy:

- custom protocol implementations;
- tightly coupled FFmpeg preview pipelines;
- compatibility layers created only for V1 migrations;
- assumptions tied to SQLite or a single process.

## 10. Non-goals for the first V2 slice

Do not start by implementing:

- PTZ;
- GB28181;
- cloud playback;
- AI inference;
- advanced alert rules;
- multi-node clustering.

The first slice should establish clean contracts and a working Camera → ZLM → Browser/Recorder path.


## 11. Optional Home Assistant integration

Home Assistant is a first-class **optional integration**, not a core dependency.

### Lightweight mode

Home Assistant automations may call authenticated zero-nvr REST endpoints directly.

Example intent:

```text
PIR / presence / door / smoke sensor
        ↓
Home Assistant Automation
        ↓
zero-nvr external trigger API
        ↓
RecordingTrigger
        ↓
Recording Policy
        ↓
pre-roll + active period + post-roll
```

### Deep integration mode

When explicitly enabled, zero-nvr may integrate through MQTT and later a Home Assistant Custom Integration.

Possible HA entities:

```text
camera online
recording state
motion/person event
recording mode
snapshot action
external recording trigger
storage/NVR health
```

MQTT remains optional. A user who does not enable this integration should not need Mosquitto.

### Recording trigger rule

External automation must express intent rather than media-process commands.

Preferred model:

```text
RecordingTrigger
  camera_id
  source
  external_id
  event_type
  state
  started_at
  last_active_at
  ended_at
  pre_roll_seconds
  post_roll_seconds
  metadata
```

Repeated sensor activity refreshes the same logical trigger session instead of repeatedly starting/stopping recorder processes.
