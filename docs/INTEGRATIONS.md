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
| MQTT broker | integration/event transport | Optional | Integration |
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
