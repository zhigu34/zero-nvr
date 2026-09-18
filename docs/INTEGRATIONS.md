# Integration Map

The project intentionally uses mature components for commodity protocol/infrastructure responsibilities.

| Component | Role | Initial status | zero-nvr boundary |
|---|---|---|---|
| ZLMediaKit | RTSP ingest, live media, protocol conversion | Core | MediaPlane adapter |
| FFmpeg / ffprobe | recording, export, inspection, conversion | Core | RecorderBackend / jobs |
| ONVIF client library | SOAP/WSDL/WS-Security, Device/Media/Events/PTZ protocol | Core | DeviceAdapter |
| PostgreSQL | authoritative metadata | Core | Persistence |
| Apprise | generic notifications | Planned | NotificationBackend |
| S3-compatible storage | remote object storage | Planned | StorageBackend |
| rclone | generic cloud-drive transfer | Optional | StorageBackend |
| OpenList | storage gateway/WebDAV | Optional | StorageBackend |
| Frigate | external AI detection | Optional | DetectionProvider |
| Home Assistant | home automation / external recording triggers / NVR state exposure | Optional | IntegrationAdapter |
| MQTT broker | deep integration / event transport / HA MQTT Discovery | Optional | IntegrationAdapter |
| coturn | WebRTC TURN | Optional | Media infrastructure |
| HIK vendor SDK | vendor-private device features | Optional | isolated DeviceAdapter bridge |
| WVP + ZLM | GB28181 | Future optional | DeviceAdapter / media integration |

## Rules

### Core does not mean authoritative

ZLMediaKit is core infrastructure, but PostgreSQL/zero-nvr remains authoritative for Camera, Recording, Event and Storage business state.

### Optional integration failure

An optional integration failure must not make unrelated core recording unavailable.

Examples:

- Frigate down → AI detections unavailable, continuous recording remains healthy.
- OpenList down → remote upload delayed, local recording continues.
- Apprise backend failure → delivery retries, event history remains.
- HIK bridge down → only cameras requiring that adapter are affected.
- Home Assistant unavailable → external automation triggers are unavailable, core recording continues.
- MQTT unavailable → MQTT-backed integrations degrade, REST/core NVR behavior continues.

### Configuration ownership

External component configuration should be generated or reconciled from zero-nvr intent where practical.

Avoid a design that requires the operator to configure the same Camera separately in:

- zero-nvr;
- ZLMediaKit;
- Frigate;
- storage gateway.

zero-nvr should orchestrate integration configuration or clearly document the source of truth.

## Live media integration

ZLMediaKit is expected to expose stable internal stream keys such as:

```text
camera/{camera_id}/main
camera/{camera_id}/preview
camera/{camera_id}/detection
```

Exact naming is an implementation detail and should not leak into business identifiers.

## AI integration

External AI should consume a preview/detection stream, not create an independent high-cost main-stream connection unless necessary.

```text
Camera
  ↓
ZLM
  ├── recorder
  ├── browser
  └── AI provider
```

AI events return through a provider adapter and normalize to DetectionEvent.

## Storage integration

A storage adapter must be able to answer:

- was the object written?
- can the object be read?
- does size/checksum match when verification is supported?
- what stable object key identifies it?
- can it be deleted safely?

These questions matter more than the underlying vendor API.


## Home Assistant integration

Home Assistant is an optional, load-on-demand integration.

### Mode A — REST-only

The lightweight path requires no broker.

Home Assistant automations call an authenticated zero-nvr endpoint with external intent such as:

```text
presence active
door opened
smoke alarm
doorbell pressed
manual automation trigger
```

zero-nvr converts that intent into a canonical DetectionEvent and/or RecordingTrigger.

Home Assistant must not receive an API that directly controls FFmpeg processes or ZLMediaKit stream internals.

### Mode B — MQTT deep integration

When explicitly enabled, MQTT may be used for:

- publishing zero-nvr camera/NVR state;
- receiving approved commands/triggers;
- Home Assistant MQTT Discovery;
- event state propagation.

Potential HA entity types include:

- binary_sensor for camera online / motion / person;
- sensor for storage/runtime health;
- switch/select for recording policy where safe;
- button for snapshot or trigger actions;
- camera entity where the HA media contract is useful.

The MQTT broker is not part of the default deployment.

### Mode C — Home Assistant Custom Integration

A future `custom_components/zero_nvr` package may provide the best UX:

```text
HA → Add Integration → Zero NVR → URL + API token
```

The custom integration should consume zero-nvr's stable public API rather than embed media/protocol business logic.

### Example automation path

```text
presence sensor = active
        ↓
Home Assistant
        ↓
External Trigger API
        ↓
RecordingTrigger
        ↓
Recording Policy
        ↓
pre-roll / active / post-roll
```

If continuous recording is already active, zero-nvr should normally annotate/promote existing segments instead of launching a duplicate recorder.
