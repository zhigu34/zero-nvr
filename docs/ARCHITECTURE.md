# zero-nvr Architecture Baseline

Status: **V1 Design Freeze Candidate**

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


## 2.1 First production release policy

The first production release is a complete long-term usable NVR product, not an MVP.

Engineering phases only define implementation order. V1 completeness is measured by an end-to-end usable NVR lifecycle: install, initialize, onboard cameras, live view, record, timeline/playback, events, retention/archive, notifications, user recovery, backup/restore, health, and safe upgrade.

Optional integrations such as Frigate, Home Assistant/MQTT, vendor-private adapters, GB28181/WVP, Prometheus/Grafana, advanced PITR, and multi-node features do not block V1 unless an explicit product decision promotes them. "Optional" may mean deployable/enableable in V1 or a documented extension point; the release-scope spec is authoritative.

See [Spec 0013 — First Production Release Scope and Completeness Policy](specs/0013-first-production-release-scope.md).

## 3. Logical planes

```text
┌─────────────────────────────────────────────┐
│                 Vue 3 UI                    │
│ Device / Live / Timeline / Event / Storage  │
└─────────────────────┬───────────────────────┘
                      │
                  HTTP / SSE
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
 Vendor opt.    FFmpeg     Frigate     Upload
 GB/WVP future  coturn     External    Export
       │          │          │          Notify
       └──────────┴──────────┴──────────┘
                         │
                 Integration Plane
                 HA / MQTT / Webhook
                         │
                      Cameras

       SQLite / PostgreSQL = metadata truth
                         │
          Local / S3 / rclone / OpenList
```

### Production database modes

zero-nvr supports two production database modes behind one persistence/domain contract.

```text
                DatabaseCapabilities
                /                  \
        SQLite (default)       PostgreSQL
        lightweight            optional scale-up
        WAL                    client/server
```

SQLite is the default for single-host lightweight deployment. PostgreSQL is available for sustained higher write concurrency and larger installations. User-visible business features stay the same.

A separate versioned SQLite portable index remains available for offline inspection/export/import independent from whichever production database is active.

See [Spec 0016 — SQLite and PostgreSQL Production Database Modes](specs/0016-postgresql-and-sqlite-portability.md).

## 4. Source-of-truth rules

### Production database

The selected SQLite or PostgreSQL production database is the authoritative metadata store for:

- devices, cameras, endpoints and connections;
- stream mappings;
- recording policies;
- recording segments;
- detection events;
- alert rules and deliveries;
- storage targets and objects;
- upload jobs;
- meaningful health state transitions/events (not high-frequency telemetry);
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
identity()
device_info()
channels()
media_profiles()
stream_uri()
event_capabilities()
ptz_capabilities()
time_capabilities()
health()
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

### Recording ownership

Normal continuous/scheduled recording is owned by ZLMediaKit.

Conceptual operations exposed through the zero-nvr media/recording adapter:

```text
start_record()
stop_record()
record_status()
list/reconcile_recordings()
```

Normal media path:

```text
Camera -> ZLMediaKit -> ZLM MP4 Recorder -> local hot storage
                                      -> on_record_mp4 -> RecordingCatalog
```

FFmpeg is not a long-lived RecorderBackend. It is used by worker jobs for derived media such as export, remux/transcode, clipping, frame extraction, inspection, and repair.

See [ADR-0002 — ZLMediaKit Owns Normal Recording](adr/0002-zlm-recording-authority.md).


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
test()
health()
capabilities()
```

First-production-release routing includes native SMTP/email, Apprise-backed providers, webhook, Home Assistant, and MQTT actions. Channel credentials remain behind SecretStore. Notification network calls run asynchronously and never block recording/event transactions.

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

### Camera/device onboarding and stream selection

Device identity is separate from Camera/channel identity.

```text
Discovery / Manual endpoint
        ↓
DiscoveryCandidate
        ↓
identity + credential probe
        ↓
Device
  ├─ DeviceEndpoint
  ├─ DeviceCredential -> SecretStore
  └─ Camera channel(s)
         ↓
  SourceMediaProfile(s)
         ↓
  recording / live_main / live_preview / detection / audio
```

Discovery only finds candidates; it does not create authoritative cameras. ONVIF, manual RTSP, HIK/vendor bridge, and GB28181/WVP normalize into the same Device/Camera/SourceMediaProfile model.

Stable device identifiers are preferred over IP address so DHCP changes do not duplicate cameras. Weak/ambiguous matches require confirmation.

Onboarding verifies actual media pull in addition to management authentication. Multi-channel NVR/DVR and multi-sensor devices create one Device with several logical Camera channels.

Automatic profile selection is explainable and overrideable. Recording, live-main, preview-grid, detection, and audio roles may map to different source profiles. Browser codec limitations do not force the recording source profile to change globally.

See [Spec 0018 — Camera Onboarding, Discovery, Capability Probe, and Stream Selection](specs/0018-camera-onboarding-discovery-and-stream-selection.md).

### Device runtime lifecycle and reconfiguration

Durable configuration and runtime state are separate.

```text
Device / Camera / MediaStream config
             ↓
       RuntimeSupervisor
      /      |       \
 control   media    event/PTZ/time
            ↓
       ZLMediaKit
            ↓
     RecordingManager
```

Runtime-relevant changes carry monotonic config revisions and short-lived runtime generations. Late callbacks from an old ZLM stream, event subscription, reconnect timer, or device probe are ignored for current-state mutation once a newer revision is authoritative.

Configuration apply follows prepare/validate/commit/apply. Metadata-only edits do not restart media. Endpoint/credential changes rebuild only affected runtimes when possible. Source-profile switches use shadow verification and safe handoff.

Recording-profile changes preserve RecordingSession and active RecordingIntents. Planned changes switch at a safe formal segment boundary; forced changes close the physical segment with `completion_reason = source_reconfigured` and start a new segment while keeping logical recording intent active.

Capability/profile/channel drift is diffed rather than treated as device deletion. Missing NVR channels keep their Camera identity/history and revive when the same stable channel returns.

See [Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift](specs/0019-device-runtime-lifecycle-and-reconfiguration.md).

### Live view, MediaSession, and adaptive delivery

Live viewing is resolved per browser/session rather than exposing a permanent ZLM/camera URL.

```text
Browser
   ↓
LiveSessionService
   ↓ auth + browser/network capabilities
LivePlaybackResolver
   ↓
MediaSession
   ↓
MediaPlane / ZLMediaKit
   ↓
Camera live_preview / live_main
```

Default transport preference is WebRTC, then fMP4, then HLS when the codec/transport combination is actually supported.

Grid tiles use `live_preview`; focused/fullscreen views may promote to `live_main`. Automatic quality uses viewport/network hints with hysteresis to avoid stream thrash.

H.265 recording remains independent from browser live compatibility. When the browser cannot directly consume the selected H.265 live source, zero-nvr first prefers a compatible H.264 source profile and otherwise may create a shared on-demand H.264 live derivative through TranscodeManager.

Remote WebRTC uses STUN/TURN; coturn is the default TURN implementation. TURN credentials are short-lived and issued only for authorized MediaSessions.

Audio playback and TalkSession are separate from video. Talk uses an adapter-specific TalkBackend for ONVIF/RTSP backchannel, HIK/vendor SDK, GB28181/WVP, or other supported device paths.

See [Spec 0020 — Live View, Media Sessions, Adaptive Quality, TURN, and Talk](specs/0020-live-view-media-session-and-talk.md).

### Live view

```text
Camera
  ↓
ZLMediaKit
  ↓
WebRTC / fMP4 / HLS
  ↓
Browser

FastAPI issues short-lived MediaSession authorization and transport/profile resolution metadata. Camera/ZLM administrative credentials never reach the browser.
```

### Continuous recording

```text
Camera
  ↓
ZLMediaKit
  ↓
ZLM MP4 Recorder
  ↓
local RecordingLocation
  ↓
on_record_mp4 hook
  ↓
RecordingSegment catalog
```

The database is not in the media hot path. If a hook is lost during a control-plane/database outage, reconciliation discovers the file and repairs the catalog later.


### Event pre-roll and segment composition

Target product semantics are fixed, but the physical pre-roll mechanism is not frozen until the design-freeze POC passes.

Required behavior:

```text
default pre-roll  ≈ 10s
default post-roll ≈ 10s
later related triggers may extend planned end time
events remain independent timeline markers
one camera does not start duplicate recorders for overlapping intents
```

Preferred implementation candidates reuse ZLMediaKit's existing rolling HLS/fMP4/GOP/recording capabilities. zero-nvr must not implement a custom H.264/H.265 packet ring buffer.

The final physical composition and fMP4 choice are validated by [V1 Design-Freeze POC Plan](plans/01-design-freeze-poc.md). Until that POC passes, older rolling-MP4/tmpfs details are candidate implementation notes rather than frozen invariants.


### Recording intent arbitration

Recording modes are additive business intents rather than mutually exclusive recorder states.

```text
continuous / schedule / event / manual intents
                    ↓
             RecordingManager
                    ↓
        one RecordingSession per
      uninterrupted formal interval
                    ↓
        one formal media pipeline
```

The camera remains in formal recording while at least one intent is active. Adding/removing intents does not restart recording or reset the 5-minute segment clock.

Important behavior:

- event during continuous/schedule/manual recording adds event markers and retention without restarting media;
- manual start during existing recording adds a manual intent only;
- manual stop removes only the manual intent;
- schedule end stops media only when no other intent remains;
- a true interval with no active intents ends the RecordingSession;
- V2 `hybrid` means scheduled baseline recording plus event-triggered recording outside schedule windows.

See [Spec 0007 — Recording Intent Arbitration and Mode Composition](specs/0007-recording-intent-arbitration.md).


### Stream loss and reconnect recovery

Transport/media failure is separated from business recording intent.

```text
camera/protocol runtime
        ↓
ZLMediaKit runtime stream
        ↓
RecordingSegment
        ↓
RecordingSession / RecordingIntent
```

A confirmed media break closes the current physical RecordingSegment and marks it with `completion_reason = source_lost` (or another explicit interruption reason). Recovery always writes a new physical file; it never appends new media into the old MP4.

If RecordingIntent still requires recording, the same RecordingSession remains active across the outage:

```text
RecordingSession  ─────────────────────────────

physical media    [segment A]    [segment B]
                              gap
```

After actual media recovery, the formal physical segment clock restarts from the recovery time. This is an exception to the normal healthy-intent rule: intent changes do not reset cadence, but real media discontinuity does.

Camera health may progress through `degraded → reconnecting → offline`, while background retry continues for enabled cameras. Historical playback exposes the actual gap such as `source_lost`.

ZLMediaKit implementation must use source/runtime signals rather than reader-count hooks; `on_stream_none_reader` is not a camera-disconnect signal.

See [Spec 0008 — Stream Loss, Reconnect, and Recording Recovery](specs/0008-stream-reconnect-and-recording-recovery.md).

### Detection providers, observations, and event fusion

Event providers do not directly become recording/alert engines.

```text
ONVIF / HIK / Frigate / local detector
                ↓
        DetectionProvider
                ↓
       DetectionObservation
                ↓
         EventNormalizer
                ↓
         DetectionEvent
          ↓            ↓
  EventFusionGroup   DetectionPolicy
                       ↓
              RecordingManager / AlertEvaluator
```

Provider observations are append-oriented source evidence. DetectionEvent is the provider-neutral business/timeline event. Cross-provider EventFusionGroup correlation is deliberately non-destructive so forensic detail can still show every provider report.

A Camera may bind multiple providers with independent timeline/recording/alert eligibility. Frigate is treated as an optional DetectionProvider; its object/event database and recordings are never zero-nvr business authority.

Provider stateful events use START/UPDATE/END with durable idempotency keys, out-of-order protection, timestamp provenance, and bounded liveness on provider disconnect. Zones map through canonical EventZone while preserving external-provider semantics.

See [Spec 0021 — Detection Providers, AI Events, Object Tracking, Zones, and Event Fusion](specs/0021-detection-providers-ai-events-and-fusion.md).

### Native / AI / external automation events

```text
Camera ONVIF/HIK
      or
Local RTSP detector
      or
Optional AI provider
      or
Optional IntegrationAdapter
(Home Assistant / MQTT / Webhook)
      ↓
Canonical DetectionEvent START / END
      ↓
RecordingManager
      ├── RecordingSession lifecycle
      ├── Event timeline marker
      └── EventLog
      ↓
Recording Policy / AlertRule
      ↓
RecorderBackend / Notification / Webhook
```

Event sources report state; zero-nvr alone owns recording execution and lifecycle. Home Assistant, MQTT, ONVIF, local detection, AI providers and similar systems must not directly start/stop FFmpeg or manipulate ZLMediaKit internals.

For stateful event recording, the accepted lifecycle is defined in [Spec 0002 — Event Recording Lifecycle](specs/0002-event-recording-lifecycle.md):

- first event START with no active recording uses the configured pre-roll (V2 default: 10 seconds);
- any ACTIVE event keeps the same event RecordingSession alive;
- after the final event END, the configured post-roll begins (V2 default: 10 seconds);
- a new event during post-roll cancels the pending stop and reuses the same RecordingSession;
- each event remains an independent timeline marker and EventLog entry even when multiple events share one recording;
- continuous/manual/schedule recording is annotated by events rather than restarted.


### Alert incidents and notification delivery

Alerting consumes canonical event/health/security signals independently from RecordingManager.

```text
DetectionEvent / Health / Security
            ↓
        AlertEvaluator
            ↓
         AlertRule
            ↓
       AlertIncident
       ├─ grouping/cooldown
       ├─ acknowledge/resolve
       └─ escalation
            ↓
       DeliveryPlanner
            ↓
       AlertDelivery
            ↓
 SMTP / Apprise / Webhook / HA / MQTT
```

AlertIncident is the human-attention lifecycle. It may group many source events without deleting them. Lifecycle state and acknowledgement are independent.

Quiet schedules and temporary AlertSilence may suppress outbound delivery while preserving source events/incidents. Escalation and retry timers are durable across restart.

AlertDelivery uses stable idempotency keys and per-attempt diagnostics. zero-nvr does not falsely promise exactly-once external delivery when a remote provider cannot guarantee it.

A failing notification channel never blocks recording, event persistence, or another healthy channel.

See [Spec 0014 — Alert Incidents, Notification Routing, Escalation, and Delivery](specs/0014-alerting-notification-and-escalation.md).

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


### Recording retention and disk pressure

Retention is metadata/claim driven rather than file-age driven.

Initial V2 defaults:

```text
continuous = 7 days
schedule   = 7 days
event      = 30 days
manual     = 30 days
```

A RecordingSegment may carry several claims at once. For example, a 5-minute continuous segment containing a motion event keeps the stronger event retention without duplicating the MP4.

Disk guard defaults:

```text
warning   80%
pressure  85%
critical  92%
emergency 96%
target    80%
```

Normal cleanup only removes expired/unprotected media. Under critical pressure, zero-nvr may evict unlocked unexpired media in this order:

```text
verified-remote local copies
→ continuous/schedule
→ event
→ manual
```

User-locked and currently writing/finalizing media is never automatically purged.

See [Spec 0005 — Recording Retention, Disk Pressure, and Safe Purge](specs/0005-recording-retention-and-purge.md).


### Backup and disaster recovery

Recording archive and system backup are separate protection layers.

```text
Recording media
   -> rclone archive
   -> verified remote RecordingLocation

SQLite
   -> Online Backup API
   -> restic

PostgreSQL
   -> pg_dump
   -> restic

Secret/bootstrap recovery
   -> RecoveryKit
   -> clean-host restore
```

System backup protects metadata, configuration, encrypted credentials, and the bootstrap material required to recover them. Recording media is governed by recording/archive policy rather than copied into every system backup.

Litestream, pgBackRest, WAL/PITR, and platform snapshots are optional advanced integrations rather than V1 dependencies.

See [Spec 0015 — Backup, Disaster Recovery, and System Migration](specs/0015-backup-disaster-recovery-and-pitr.md).

### Upgrade, schema migration, and rollback

V1 host mutation is driven by the deployment interface:

```text
./deploy.sh update
```

The update path performs preflight, creates a verified database/restic safety point when required, pulls pinned images, runs Alembic migrations, starts services, checks health, and reconciles media/catalog state.

SQLite uses Online Backup before incompatible migration work. PostgreSQL uses pg_dump + restic for the V1 safety point. Cross-database SQLite <-> PostgreSQL migration is a separate operation and is never silently bundled into a normal update.

The web UI may report versions and compatibility, but it does not need Docker-socket access or a second self-update orchestrator.

Database rollback never auto-deletes media newer than the restored metadata point.

See [Spec 0017 — Upgrade, Schema Migration, Database Migration, and Rollback](specs/0017-upgrade-migration-and-rollback.md).

### Historical playback

Historical playback is driven by absolute time, not MP4 file order.

```text
Timeline Query
     ↓
PlaybackTimeline
     ├── playable RecordingSegments
     ├── explicit Gaps / reasons
     └── DetectionEvent markers
     ↓
Master Playback Clock
     ↓
Playback Resolver
     ├── Local
     ├── Cached Remote
     └── Remote signed/proxied
     ↓
Single / Multi-camera Browser Players
```

Playback API timestamps use UTC Unix milliseconds. The frontend maps absolute time to a RecordingSegment and relative media offset only at the playback boundary.

Multi-camera playback uses one Master Clock. Default `tolerant` synchronization allows healthy cameras to continue when one camera buffers; optional `strict` synchronization pauses/re-aligns participating playable cameras for forensic comparison.

Known gaps distinguish states such as not scheduled, no event, source loss, runtime restart, storage failure, missing media, and purged media. Event markers aggregate at wide zoom and expand to individual events at close zoom.

The initial browser implementation may use dual HTML video players to preload the next 5-minute file, but the timeline/domain contract must allow later upgrade to MSE/fMP4/virtual playlists without redesign.


Detailed segment lists are ordered by absolute start time and playback seek uses indexed/binary lookup. At wide zoom, a true gap that is smaller than a display pixel may be visually smoothed so file/timestamp jitter does not create flickering seams; the authoritative gap data is never modified by this rendering optimization.

Dual-player switching preloads the next logical segment and changes players at the absolute segment boundary. Strict synchronization barriers only include cameras expected to have playable media at the current Master Clock time; legitimate timeline gaps never freeze other channels.

See [Spec 0006 — Historical Playback Timeline and Multi-Camera Sync](specs/0006-historical-playback-timeline.md).


### Canonical time and camera clock handling

zero-nvr uses server/NVR UTC as canonical business/media time. Camera clocks are measured external clocks, not timestamp authority.

```text
canonical UTC
   ├─ RecordingSegment / RecordingSession / DetectionEvent
   ├─ historical playback / multi-camera Master Clock
   └─ storage/index metadata

camera clock
   ├─ monitored offset/quality
   ├─ optional ONVIF/NTP management
   └─ device-originated event timestamp correction

recording timezone
   └─ human filename / UI / wall-clock schedule presentation
```

Recording filenames are generated from canonical RecordingSegment UTC converted to the effective recording timezone; they are never generated from camera wall-clock time.

Compatible devices may be monitored through ONVIF device-time APIs. Default mode is monitor-only; optional managed NTP/timezone configuration is an explicit administrative action.


System time settings provide a recording timezone plus the default NTP source for managed cameras. Cameras in `manage_ntp` mode inherit these settings unless they have an explicit device override. zero-nvr may configure compatible cameras, but initial V2 only monitors the host operating-system NTP/time-sync state and does not reconfigure chrony/systemd-timesyncd/ntpd itself.

Device event timestamps preserve source time and receive time. A reliable measured camera-clock offset may normalize the canonical event occurrence timestamp. Historical normalized timestamps are not silently rewritten if the camera clock is corrected later.

Schedules retain local wall-clock intent through an explicit schedule timezone. Elapsed timers/retry/post-roll use monotonic clocks so host NTP corrections do not distort durations.

See [Spec 0009 — Canonical Time, Camera Clock Offset, and Timezone Handling](specs/0009-time-and-camera-clock.md).


### Recording storage targets

Direct formal recording writes to an explicit local/host-mounted `StorageTarget`. zero-nvr does not create a RAID/JBOD layer, aggregate disks, or run a custom multi-disk placement scheduler.

```text
Camera / RecordingPolicy
        -> selected LOCAL_RECORDING StorageTarget
        -> ZLMediaKit recorder
```

If several disks should behave as one volume, use mature host/storage tooling such as ZFS, Btrfs, LVM, mergerfs, hardware/software RAID, or a NAS filesystem and expose the resulting mounted path to zero-nvr.

Multiple local StorageTargets may exist for explicit routing or migration, but V1 does not automatically balance or fail over between them. A local target failure is surfaced as recording/storage health degradation; remote S3/rclone/OpenList storage remains asynchronous archive and never becomes implicit hot-recording failover.

See [Spec 0010 — Recording Storage Targets and Host-Managed Storage](specs/0010-recording-storage-pool-and-failover.md).

### Recording storage layout

Canonical local recording storage is both database-safe and independently human-browsable:

```text
recordings/
  {name_id}/
    {YYYY-MM-DD}/
      {name_id}_{YYYY-MM-DD}_{HH-MM-SS}.mp4
```

For example, a user mounting the disk without zero-nvr can browse directly by `摄像头名称ID → 日期 → 开始时间`. The database timeline remains authoritative for product behavior.

Canonical database timestamps remain UTC; every directory date and filename time is generated in the effective configured recording timezone so it matches the expected camera wall-clock/OSD time. Formal segment cadence is never reset at midnight. A healthy 5-minute RecordingSegment may cross a local date boundary and remains one file under its configured-timezone start date.

Incomplete media is written under a staging/temp path and published to the canonical path only after finalize/verification. Each camera recording directory also keeps a convenience `_camera.json` identity file for detached-disk use.

See [Spec 0004 — Recording Storage Layout and Time Index](specs/0004-recording-storage-layout.md).




### Configuration and secret management

Ordinary configuration and recoverable credentials use different storage paths.

```text
ordinary config
   → PostgreSQL

recoverable secret
   → secret_ref
   → SecretStore
   → encrypted SecretRecord in PostgreSQL
   → per-record DEK
   → externally supplied/persisted KEK keyring
```

Initial V2 uses authenticated envelope encryption for recoverable secrets. Business rows store only opaque `secret_ref` values; public/read APIs expose configured state rather than plaintext.

Verifier-only credentials such as local user passwords and authentication tokens are one-way hashed instead of reversibly encrypted.

The KEK/keyring that unlocks SecretStore is a bootstrap/deployment secret and never lives in the same PostgreSQL database as the encrypted SecretRecords. Compose deployments prefer secret files/`*_FILE` bootstrap settings over production plaintext environment variables.

Credential replacement preserves the previous working secret until the new value is validated and committed where practical. Logs, traces, EventLog, and AuditEvent redact credentials and credential-bearing URLs.

Database backups contain ciphertext but not the KEK. Normal configuration/support exports exclude secrets. An explicit privileged portable backup may include secrets only inside a separate strongly encrypted export.

See [Spec 0012 — Configuration, Secret Storage, Key Rotation, and Backup](specs/0012-config-secrets-key-management.md).

### Authentication, authorization, and audit

Authorization uses two independent dimensions:

```text
Role / Permission
      +
Camera Scope
      ↓
effective authorization
```

Initial built-in roles are Administrator, Operator, and Viewer. Permissions remain action-oriented so viewing footage does not automatically grant export/download, lock, delete, PTZ, camera management, or system administration.

Camera scope may include all cameras, selected CameraGroups, selected Cameras, or none. Backend authorization is authoritative; hiding a button in Vue is only a usability layer.

Live/playback media access uses short-lived scoped media/session authorization rather than exposing permanent stream URLs or camera credentials. Export/download/delete/lock and system/storage/security changes use explicit permissions.

External integrations use dedicated least-privilege service principals rather than administrator browser sessions.

Sensitive actor-driven changes produce append-oriented AuditEvents. Runtime/business behavior remains in EventLog; AuditEvent answers who did what, to which resource, with what result.

See [Spec 0011 — Authentication, Camera-Scoped Authorization, and Audit](specs/0011-auth-authorization-and-audit.md).

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

### External event / trigger rule

External automation must express event state or recording intent rather than media-process commands.

Stateful sensor input should normalize into canonical DetectionEvent START/END transitions. RecordingManager then decides whether to start, keep, extend, or leave an existing recording unchanged.

Repeated sensor activity belonging to the same logical active event must not repeatedly start/stop recorder processes or create duplicate timeline markers.

Recording policy owns pre-roll/post-roll. Detector/provider-specific thresholds and hold timers belong to detection/event normalization and must not be reused as recording duration.

See [Spec 0002 — Event Recording Lifecycle](specs/0002-event-recording-lifecycle.md).


## Deployment runtime boundary

The default non-AI Core is intentionally small:

```text
zero-nvr        # API
zero-nvr-worker # same image, different command
ZLMediaKit
```

This is 2 images / 3 containers.

FFmpeg, rclone, restic, Apprise, ONVIF libraries, and OIDC/auth libraries are integrated into the zero-nvr runtime/worker image where practical. Frigate, OpenList, PostgreSQL, and Mosquitto are separately deployed only when their independent service boundary is actually needed.

Deployment is driven by `deploy.sh + .env + Docker Compose Profiles`. Disabled optional services are not pulled or started, and the web application does not directly control Docker.

See [Project Baseline](PROJECT_BASELINE.md), [Deployment Architecture](DEPLOYMENT.md), and [ADR-0001](adr/0001-runtime-boundaries-and-container-policy.md).
