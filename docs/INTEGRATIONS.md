# Integration Map

The project intentionally uses mature components for commodity protocol/infrastructure responsibilities.

| Component | Role | Initial status | zero-nvr boundary |
|---|---|---|---|
| ZLMediaKit | RTSP ingest, live media, protocol conversion | Core | MediaPlane adapter |
| FFmpeg / ffprobe | export, clip/remux/transcode, frame extraction, recovery inspection | Built-in toolchain | Worker jobs |
| ONVIF client library | SOAP/WSDL/WS-Security, Device/Media/Events/PTZ protocol | Core | DeviceAdapter |
| SQLite / PostgreSQL | authoritative metadata (SQLite default, PostgreSQL optional) | Core / optional scale-up | Persistence |
| Apprise | generic notifications | First release | NotificationBackend |
| S3-compatible storage | remote object storage | First release | StorageBackend |
| rclone | remote copy/verify/delete/restore | Built-in worker tool | Storage adapter / jobs |
| OpenList | storage gateway/WebDAV | First release · optional runtime | StorageBackend |
| Frigate | external AI detection | First release · optional runtime | DetectionProvider |
| Home Assistant | home automation / external recording triggers / NVR state exposure | First release · optional runtime | IntegrationAdapter |
| MQTT broker | deep integration / event transport / HA MQTT Discovery | First release · optional runtime | IntegrationAdapter |
| coturn | WebRTC TURN | First release · optional runtime | Media infrastructure |
| HIK vendor SDK | vendor-private device enhancements | Optional extension · non-blocking | isolated DeviceAdapter bridge |
| WVP + ZLM | GB28181 | Future optional extension · non-blocking | DeviceAdapter / media integration |

## Rules

### Core does not mean authoritative

ZLMediaKit is core infrastructure, but the selected zero-nvr database (SQLite by default, PostgreSQL optionally) remains authoritative for Camera, Recording, Event and Storage business state.

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


## Integration credentials and SecretStore

Integration configuration separates non-secret endpoint/settings data from credentials.

Examples:

```text
Home Assistant URL        -> ordinary configuration
Home Assistant token      -> secret_ref

MQTT host/topic           -> ordinary configuration
MQTT username/password    -> secret_ref

S3 endpoint/bucket        -> ordinary configuration
S3 access/secret key      -> secret_ref

OpenList URL/path         -> ordinary configuration
OpenList token/password   -> secret_ref
```

Adapters request recoverable credentials through SecretStore only when they need to establish an external connection. Integration credentials are never copied into public API responses, EventLog, AuditEvent, or normal support/config exports.

Dedicated service/API credentials that zero-nvr only needs to verify should be stored as one-way verifiers rather than recoverable plaintext.

See [Spec 0012 — Configuration, Secret Storage, Key Rotation, and Backup](specs/0012-config-secrets-key-management.md).

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

AI events return through a provider adapter and normalize to Event.

## Storage integration

A storage adapter must be able to answer:

- was the object written?
- can the object be read?
- does size/checksum match when verification is supported?
- what stable object key identifies it?
- can it be deleted safely?

These questions matter more than the underlying vendor API.


## Home Assistant integration

Home Assistant is implemented in the first production release and remains optional/load-on-demand at runtime.

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

zero-nvr converts that intent into a canonical Event and, when recording policy matches, a RecordingTrigger.

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

The first production release includes a `custom_components/zero_nvr` package for the best UX:

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


## SMTP / email integration

SMTP is a first-production-release platform integration.

Uses include:

- self-service password reset;
- account/security notifications;
- event/alert email delivery;
- storage/system health notifications;
- optional export/report completion notifications.

Configuration includes host, port, STARTTLS/TLS mode, username, SecretStore-backed password, From address/name, Reply-To, timeouts, and feature toggles.

Required behavior:

- test connection;
- send test email;
- queue delivery;
- retry transient failures;
- retain delivery result/error metadata without logging credentials;
- support authenticated STARTTLS and implicit TLS;
- allow explicit no-TLS only for trusted local relays.

SMTP failure never blocks recording or event persistence.


## Alert and notification routing

External channels are NotificationTargets behind the Alert / NotificationDelivery pipeline rather than direct side effects inside Event or recording transactions.

```text
Event
  ↓
AlertPolicy
  ↓
Alert
  ↓
NotificationDelivery
  ├─ SMTP
  ├─ Apprise
  ├─ Webhook
  └─ MQTT
```

Cooldown affects repeated outbound delivery only; it never removes canonical Events or stops recording.

Each target has independent health/retry state and SecretStore-backed credentials as needed.

See [Spec 0014 — Alerts and Notifications](specs/0014-alerting-notification-and-escalation.md).

## Device identity across protocol adapters

ONVIF, HIK/vendor bridge, and GB28181/WVP are discovery/control sources rather than separate business identities.

If multiple adapters represent the same physical device, zero-nvr correlates them into one canonical Device where stable identity evidence is sufficient.

A Device may use a primary management adapter plus a supplemental vendor adapter. Multi-channel devices normalize into several Camera channels under one Device.

If a future WVP/GB28181 adapter is enabled, WVP restart/re-registration must not create new Camera IDs when canonical identity remains the same.

See [Spec 0018 — Camera Onboarding, Discovery, Capability Probe, and Stream Selection](specs/0018-camera-onboarding-discovery-and-stream-selection.md).


## Frigate AI provider contract

Frigate is the primary V1 optional AI provider.

Preferred managed flow:

```text
Camera main/sub
   -> ZLMediaKit
   -> AI_DETECT internal stream
   -> Frigate
   -> FrigateAdapter
   -> Event
```

The adapter maps Frigate camera identity explicitly to zero-nvr Camera IDs.

Frigate event IDs are preserved as provider source_event_id so new/update/end messages UPSERT one canonical Event.

Frigate HTTP/MQTT integration may be used according to the supported Frigate version for event updates, health, detail, and snapshots.

Frigate zones/labels/confidence/snapshot references are normalized only as far as zero-nvr needs for search, timeline, recording policy, Alerts, and UI.

Frigate recordings/retention remain outside zero-nvr authority; zero-nvr continues to use ZLM RecordingSegment/RecordingLocation as its recording truth.

See [Spec 0021 — Detection Providers, AI Events, and Frigate Integration](specs/0021-detection-providers-ai-events-and-fusion.md).
