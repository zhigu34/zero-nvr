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
- storage policy and RecordingLocation lifecycle;
- archive/restore orchestration;
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

zero-nvr supports one logical SQLAlchemy/Alembic domain model on two production database choices:

```text
SQLite (default)
  lightweight single-host
  WAL
  no separate DB service

PostgreSQL (optional)
  scale-up path
  client/server
  managed or external
```

SQLite is the default for single-host lightweight deployment. PostgreSQL is available when measured write concurrency or deployment requirements justify it. User-visible business features stay the same. Backend-specific behavior stays in small persistence helpers rather than a heavyweight DatabaseCapabilities framework.

[POC-09 — SQLite Load](poc-results/09-sqlite-load.md) validates the 8-camera baseline and 16-camera extended mixed Recording/Event/Timeline/retention/backup workload with WAL and zero final lock failures on the tested 4-CPU runner. After a first-run planner issue, the frozen retention indexes/query reduced p95 from seconds to about 12.11 ms (8 cameras) and 11.31 ms (16 cameras), with EXPLAIN showing a camera/end-time covering scan plus segment-keyed location lookup. Retention remains background/batched work and never holds a write transaction across storage/rclone operations.

A separate versioned SQLite portable index remains available for offline inspection/export/import independent from whichever production database is active.

See [Spec 0016 — SQLite and PostgreSQL Production Database Modes](specs/0016-postgresql-and-sqlite-portability.md).

## 4. Source-of-truth rules

### Production database

The selected SQLite or PostgreSQL production database is the authoritative metadata store for:

- devices, cameras, endpoints and connections;
- stream mappings;
- recording policies;
- recording segments and RecordingLocations;
- canonical Events, including meaningful system-health transitions;
- AlertPolicy / Alert / NotificationDelivery;
- StorageTargets and retention/protection policy;
- users, permissions and audit records;
- backup/configuration product state.

High-frequency health samples, cache state, ZLM runtime details, and queue internals are not authoritative business tables.

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

All provider outputs normalize into canonical Event.

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

Durable Camera/Device configuration and observed runtime are separate.

```text
Device / Camera configuration
             ↓
      RuntimeReconciler
       /      |      \
    ONVIF    ZLM    optional provider
             ↓
        observed health
```

RuntimeReconciler is thin and idempotent. It applies desired configuration through mature adapters, observes ZLM/ONVIF/provider state, and fences stale asynchronous results when configuration revisions race.

It does not own RTSP packet monitoring, reconnect backoff, media decoding, or a second recorder. ZLMediaKit remains responsible for source pull/reconnect and recording runtime.

Metadata-only edits should not restart media. Endpoint/credential/profile changes validate and apply only the minimum affected adapter configuration. A recording-profile switch prefers a safe segment boundary where practical; any actual media discontinuity becomes a real new RecordingSegment/gap.

Capability/profile/channel drift is diffed rather than treated as Camera deletion.

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

TURN/coturn is optional for deployments that need remote WebRTC traversal. LAN-only V1 does not depend on it.

Audio playback is capability-dependent. Two-way talk is also optional and uses mature ONVIF/RTSP/vendor backchannel support when implemented; talk failure never affects video or recording.

See [Spec 0020 — Live View, Media Sessions, Compatibility, Audio, and Optional Talk](specs/0020-live-view-media-session-and-talk.md).

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
ZLM fMP4 Recorder
  ↓
local RecordingLocation
  ↓
on_record_mp4 hook
  ↓
RecordingSegment catalog
```

The V1 default recorder container mode is fMP4, validated by [POC-02](poc-results/02-fmp4-crash.md) for materially better interrupted-file recovery than ordinary MP4 under the tested SIGKILL scenario.

The database is not in the media hot path. If a hook is lost during a control-plane/database outage, reconciliation discovers the file and repairs the catalog later.

[POC-10 — Recovery Reconciliation](poc-results/10-reconciliation.md) validates this boundary under FastAPI restart, SQLite write lock, missed hooks, stale metadata, provable/ambiguous orphan media, and reconciliation-process interruption. The accepted behavior is recover-provable, mark-missing, preserve-ambiguous, and converge idempotently.


### Event pre-roll and segment composition

The V1 physical pre-roll mechanism is accepted from [POC-03](poc-results/03-event-preroll.md) and [POC-04](poc-results/04-multi-event-extension.md).

Required behavior:

```text
default pre-roll  ≈ 10s
default post-roll ≈ 10s
later related triggers may extend planned end time
events remain independent timeline markers
one camera does not start duplicate recorders for overlapping intents
```

The accepted V1 design keeps one ordinary ZLMediaKit recorder continuously writing short finalized fragments into a bounded shared tmpfs. Event/RecordingTrigger state changes only which overlapping finalized fragments are protected and promoted to the persistent LOCAL RecordingTarget.

```text
Camera
  -> ZLM normal recorder
  -> bounded tmpfs short fragments
  -> on_record_mp4
  -> Event window overlap
  -> copy / verify / atomic publish
  -> RecordingSegment + RecordingLocation
```

This keeps the ordinary ZLM MP4Recorder/hook/reconciliation path and naturally handles unknown Event duration without recorder restart. Whole overlapping fragments may contain extra media before/after the exact Event window; Timeline/Event timestamps remain exact, while exact trimming is an Export concern.

Two additional ZLM-native approaches were retained only as comparison/fallback mechanisms:

- `startRecordTask(back_ms, forward_ms)`, which currently creates an independent fixed-duration recording task per call;
- ordinary `startRecord` after pre-creating ZLM's frame GOP Ring.

POC-03 confirmed repeated `startRecordTask` calls create independent fixed clips rather than one extendable event task, while GOP-ring `startRecord` can recover history but exposes unsuitable raw Hook absolute timing for the canonical V1 event timeline. Neither replaces the rolling-tmpfs baseline.

zero-nvr must not implement a custom H.264/H.265 packet ring buffer or a second permanent event recorder.

The mechanism, H.264/H.265 coverage, overlapping-trigger behavior, tmpfs boundedness, and control-plane-restart reconstruction are validated by POC-03/04 and frozen in [Spec 0003](specs/0003-rolling-mp4-prebuffer.md). The exact production fragment target and per-deployment tmpfs size remain configurable operational parameters. POC-02 separately selected fMP4 as the V1 default recorder container mode.


### Recording arbitration

Recording requirement is derived rather than represented by a mandatory RecordingIntent/RecordingSession persistence model.

```text
RecordingPolicy
  continuous/schedule baseline
        +
active RecordingTriggers
  event/manual/API
        ↓
per-camera recording arbiter
        ↓
one desired recorder state
        ↓
ZLMediaKit recorder
```

Important behavior:

- continuous/schedule/event/manual reasons are additive;
- adding/removing one reason never starts a duplicate recorder;
- event during existing recording adds Event/Trigger/retention semantics without creating another MP4;
- manual stop removes only the manual trigger/reason;
- schedule end stops recording only if no other reason remains;
- actual finalized media is represented only by RecordingSegment.

See [Spec 0007 — Recording Intent Arbitration](specs/0007-recording-intent-arbitration.md).

### Stream loss and reconnect recovery

ZLMediaKit owns source pull and reconnect runtime.

zero-nvr observes media registration/recorder state and projects product health:

```text
ONLINE
DEGRADED
OFFLINE
DISABLED
```

A real interruption ends the current finalized media coverage. After recovery, new media uses actual recovery timestamps and any missing interval remains a real timeline gap.

If policy/active triggers still require recording, zero-nvr simply reconciles desired recorder state after ZLM/source recovery. It does not preserve a synthetic RecordingSession object across the outage or run a competing reconnect engine.

See [Spec 0008 — Stream Loss, Runtime Recovery, and Recording Reconciliation](specs/0008-stream-reconnect-and-recording-recovery.md).

### Historical playback

Historical playback is driven by absolute time, not MP4 file order.

```text
Timeline Query
     ↓
PlaybackTimeline
     ├── playable RecordingSegments
     ├── explicit Gaps / reasons
     └── Event markers
     ↓
Master Playback Clock
     ↓
Playback Resolver
     ├── local AVAILABLE RecordingLocation -> ZLM VOD
     └── remote AVAILABLE RecordingLocation -> rclone restore cache -> ZLM VOD
     ↓
Single / Multi-camera Browser Players
```

The remote branch above is validated by [POC-07 — Remote Restore Playback](poc-results/07-remote-restore.md). V1 does not require FUSE/rclone mount for remote-only playback.

Playback API timestamps use timezone-aware ISO 8601 strings. The frontend converts them to epoch milliseconds internally for timeline math, then maps absolute time to a RecordingSegment and relative media offset only at the playback boundary.

RecordingSegment absolute coverage is normalized at the ZLM adapter/catalog boundary. Within one proven continuous ZLM media session, a known next-segment boundary plus the current segment's actual muxed duration resolves startup/keyframe bias. ZLM source unregister/re-register always splits timing sessions, so normalization never bridges real source loss.

See [ADR 0011 — Normalize ZLM Recording Time Within Proven Media Sessions](adr/0011-zlm-recording-time-normalization.md) and [POC-05](poc-results/05-timeline-precision.md).

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
   ├─ RecordingSegment / Event / RecordingTrigger
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

Ordinary product settings live in the selected product database.

Recoverable credentials use opaque `secret_ref` values pointing to encrypted SecretRecord rows:

```text
business row
   -> secret_ref
   -> SecretStore
   -> authenticated-encrypted SecretRecord

deployment bootstrap
   -> ZERO_NVR_SECRET_KEY / *_FILE
   -> key material kept outside the product DB
```

V1 uses mature cryptographic libraries such as Python `cryptography`/Fernet/MultiFernet or equivalent. It does not require a custom DEK/KEK envelope-encryption protocol.

Verifier-only credentials such as local passwords, Personal API Tokens, and reset tokens are one-way hashed.

Logs, traces, Event/Audit metadata, and normal configuration exports never expose secret plaintext. Disaster recovery preserves the external key material required to decrypt restored SecretRecords.

See [Spec 0012 — Configuration and Secret Storage](specs/0012-config-secrets-key-management.md).

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

Sensitive actor-driven changes produce append-oriented AuditEvents. Runtime/business occurrences use canonical Event rows (including source=system where appropriate); AuditEvent answers who did what, to which resource, with what result.

See [Spec 0011 — Authentication, Camera-Scoped Authorization, and Audit](specs/0011-auth-authorization-and-audit.md).

## 7. Runtime roles

The default Core deployment is intentionally small:

```text
Image: zero-nvr
  ├─ container: zero-nvr-api
  │    FastAPI + built Vue static assets
  └─ container: zero-nvr-worker
       Huey + FFmpeg/ffprobe + rclone + restic + Apprise

Image: ZLMediaKit
  └─ container: zlmediakit
```

Default non-AI Core therefore targets **2 images / 3 containers**.

SQLite is embedded and is the default production database. PostgreSQL is an optional managed/external service, not a Core container requirement.

Optional independently running services may include:

```text
frigate
mosquitto
openlist
postgres
coturn
vendor bridge        # when genuinely required
wvp                  # future GB28181 extension
```

Small libraries and CLI tools do not receive separate containers merely for conceptual modularity. Optional managed services are not pulled or started unless enabled by deployment configuration.

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

Stateful sensor input should normalize into canonical Event new/update/end state. Recording policy evaluation creates/updates RecordingTrigger when media retention/recording is required.

Repeated sensor activity belonging to the same logical active event must not repeatedly start/stop recorder processes or create duplicate timeline markers.

Recording policy owns pre-roll/post-roll. Detector/provider-specific thresholds and hold timers belong to detection/event normalization and must not be reused as recording duration.

See [Spec 0002 — Event Recording Lifecycle and RecordingTrigger](specs/0002-event-recording-lifecycle.md).


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
