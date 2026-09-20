# zero-nvr Project Baseline

Status: **V1 Design Freeze Candidate**

This file is the highest-level engineering baseline for zero-nvr. When another document conflicts with this file, this file wins until the conflict is resolved by an explicit architecture decision.

## Product target

zero-nvr is a lightweight but complete self-hosted NVR for home, personal, NAS/home-server, small-office, and small-to-medium camera deployments.

The first stable release must be usable end-to-end rather than a demo/MVP. Completeness means that the normal lifecycle has no functional dead end: install, initialize, add cameras, record, play back, inspect events, retain/archive, notify, back up, restore, and upgrade.

## Core engineering principles

1. **Mature components first.** Reuse proven media, protocol, transfer, notification, backup, and identity libraries/tools instead of reimplementing them.
2. **One clear owner per capability.**
   - ZLMediaKit: camera ingest, media routing, live delivery, MP4 recording, VOD.
   - Frigate: optional AI detection/tracking.
   - FFmpeg/ffprobe: on-demand derived-media work only.
   - rclone: remote file transfer/verification/restore.
   - OpenList: optional adapter for storage providers awkward to access directly with rclone.
   - restic: disaster/system backup repository transport and dedup/encryption.
   - Huey: background tasks/scheduling.
   - Apprise: notification delivery.
   - mature ONVIF/WS-Discovery libraries: camera protocol access.
3. **zero-nvr owns the product control plane and canonical business model**, not commodity protocol implementations.
4. **Modular monolith.** FastAPI + Vue + worker; do not split zero-nvr itself into microservices without a proven need.
5. **SQLite is the default production database.** PostgreSQL is optional for larger deployments; user-facing features remain equivalent.
6. **Frontend talks only to zero-nvr /api/v1.** Browsers do not directly administer ZLM, Frigate, rclone, OpenList, or databases.

## Runtime and container boundary

A feature does **not** deserve a container merely because it is a separate capability.

Small libraries and CLI tools should be integrated into the zero-nvr runtime/worker image when practical:

- FFmpeg / ffprobe
- rclone
- restic
- Apprise
- ONVIF / WS-Discovery client libraries
- Authlib and other auth libraries

A separate container is justified when the component is an independently running service with its own lifecycle, resource/hardware boundary, port/protocol surface, or upgrade boundary.

Typical separately deployed services:

- ZLMediaKit
- Frigate (optional)
- OpenList (optional managed mode)
- PostgreSQL (optional managed mode)
- Mosquitto (optional managed MQTT)

### Core deployment target

Default non-AI deployment:

- **2 images**
- **3 containers**
  - zero-nvr API
  - zero-nvr worker
  - ZLMediaKit

The API and worker use the same zero-nvr image with different commands. Enabling normal remote archive does not add an rclone container; the worker invokes rclone directly.

## Deployment model

Primary deployment interface:

```text
deploy.sh + .env + Docker Compose Profiles
```

Rules:

- optional components are not pulled and not started unless enabled;
- deployment-level availability is controlled by .env / Compose profiles / deploy.sh;
- product-level enablement and configuration are controlled by the zero-nvr UI/database;
- the web application must not require direct Docker socket access;
- external services are supported where practical instead of forcing duplicate managed services.

Expected deploy.sh direction:

```text
./deploy.sh install
./deploy.sh update
./deploy.sh status
./deploy.sh doctor
./deploy.sh feature enable <name>
./deploy.sh feature disable <name>
./deploy.sh admin reset-password
./deploy.sh backup
./deploy.sh restore
```

## Reliability priority

When trade-offs are required, preserve capabilities in this order:

```text
recording reliability
> historical-data integrity
> live preview
> events/alerts
> AI
> export/thumbnails/derived assets
```

Consequences:

- Frigate failure must not stop normal recording.
- OpenList/rclone/archive failure must not stop local recording.
- notification failure must not lose Event/Alert state.
- FastAPI/worker/database short outages should not terminate an already-running ZLM recording session when avoidable.
- ZLM is the media runtime; zero-nvr reconciles desired product state after control-plane recovery.

## Recording authority

Normal continuous and scheduled recording are owned by **ZLMediaKit's recorder**.

Do not use a permanent per-camera FFmpeg recording process for normal recording.

Normal path:

```text
Camera -> ZLMediaKit -> ZLM MP4 Recorder -> local hot storage
                                      -> on_record_mp4 -> RecordingCatalog
```

FFmpeg is reserved for derived work such as export, clip/concat/remux, compatibility transcode, historical frame extraction, repair, and fallback inspection.

Recording media files and the product catalog are **eventually consistent**. A missed hook must be recoverable through reconciliation; the database must not be placed in the media hot path.

## Event recording and trigger model

The canonical data model includes **RecordingTrigger** with a correlation identifier and source evidence.

At minimum it must preserve:

- trigger type
- source/provider
- source event id
- requested time
- pre-roll/post-roll
- planned recording window
- state
- reason
- correlation_id
- metadata

Multiple events may extend one logical recording window without starting duplicate recorders. Events remain independent timeline markers.

### Pre-roll is not frozen yet

The ~10 second EVENT_ONLY pre-roll implementation is a **POC gate**, not a frozen implementation.

Preferred candidates use ZLMediaKit's own rolling media/GOP/HLS/fMP4 capabilities. zero-nvr must not implement a custom H.264/H.265 packet ring buffer.

## Recording format validation

ZLMediaKit fMP4 recording (`record.enableFmp4=1`) is a preferred candidate because of crash/power-loss resilience, but it becomes the default only after validation of:

- abnormal termination recovery;
- ZLM VOD/seek;
- browser playback path;
- FFmpeg export/remux;
- archive/restore.

## Storage lifecycle

Remote archive is asynchronous and never part of the live recording hot path.

Default archive transition:

```text
local AVAILABLE
-> rclone copy/copyto
-> verify
-> remote RecordingLocation AVAILABLE
-> retention may delete local copy
```

Do not use `rclone move` as the default product workflow. Do not use whole-tree sync semantics that can mirror local retention deletion into remote archive unintentionally.

Protected recordings are never silently deleted. If disk pressure cannot be resolved without violating explicit protection/retention requirements, raise a critical condition and sacrifice new recording before silently destroying protected evidence.

## Remote playback

V1 default for remote-only media:

```text
remote RecordingLocation
-> rclone restore/copyto
-> bounded local playback cache
-> ZLMediaKit VOD
-> browser
```

The V1 baseline does not require FUSE/rclone mount. Mount/VFS/serve-http streaming may be added later as an optimization after compatibility validation.

## Time model

- persisted canonical timestamps: UTC;
- public API timestamps: ISO 8601 with timezone;
- UI: configured system/user timezone;
- host clock synchronization health is observable;
- camera clock offset is measured when supported;
- camera NTP/time configuration uses mature device/ONVIF capabilities;
- zero-nvr does not implement an NTP server.

Time/NTP and camera clock-offset health are first-release features.

## Backup and recoverability

System backup and recording archive are separate concerns.

System disaster backup protects non-reproducible product data and secrets:

- SQLite online backup or pg_dump as appropriate;
- restic for encrypted/versioned backup repository handling;
- master key / secret-key recovery material must be preserved according to the secret-store design.

Disposable/reproducible data is excluded from normal system backup:

- thumbnails
- export cache
- playback cache
- rclone cache
- current in-memory health state
- Timeline/Gap projections

Backup success must be accompanied by integrity verification policy; restore must be testable.

## Health model

Health is capability-specific, not one global red light.

Examples:

- camera online / recording normal / AI unavailable;
- recording normal / archive degraded;
- API healthy / optional integration unavailable.

Current health may live in memory; persist meaningful state transitions/events, not high-frequency telemetry in SQLite.

## External mode

Where practical, optional dependencies support managed and external operation:

- Frigate
- MQTT
- OpenList
- PostgreSQL
- OIDC provider
- SMTP relay

Users who already operate a service should not be forced to start a duplicate service.

## First-run initialization

The first-run UI should cover:

1. administrator creation;
2. timezone and host NTP/time health;
3. local recording storage;
4. camera onboarding;
5. recording policy;
6. optional integrations/features;
7. completion/health verification.

If a deployment-level component is unavailable, the UI reports it and points to the deploy.sh feature command rather than controlling Docker directly.

## Performance/resource targets

Targets to validate, not assumptions:

- baseline: 8 cameras;
- extended target: 16 cameras;
- Core static application/image footprint target: **< 2 GB**;
- Core idle RAM target: **< 1 GB**, excluding Linux page cache and large ZLM media buffers;
- SQLite must remain a first-class supported production mode.

Measurement/accounting rules and the 2–4 camera small-host soak are defined in [Plan 04 — V1 Resource Budget](plans/04-v1-resource-budget.md). Recording media and configured disposable cache capacity are reported separately from static Core footprint.

## V1 scope guard

Do not block the first stable release on infrastructure that is not required for a complete lightweight NVR, including:

- Kubernetes;
- multi-node media cluster/HA;
- GB28181 unless explicitly re-promoted by product decision;
- advanced vendor-private integrations beyond needed standard functionality;
- advanced face/LPR AI features;
- mandatory Prometheus/Grafana deployment;
- mandatory rclone FUSE streaming.

These can exist as optional/future integrations without weakening the V1 product lifecycle.

## Design-freeze gate

The architecture remains **V1 Design Freeze Candidate** until the following POCs pass:

1. ZLM continuous recording + on_record_mp4 indexing;
2. fMP4 abnormal termination/crash recovery;
3. EVENT_ONLY pre-roll;
4. multi-event recording-window extension;
5. recording wall-clock/timeline precision;
6. ZLM VOD seek;
7. remote restore -> cache -> ZLM playback;
8. ZLM stream sharing and expected camera connection count;
9. SQLite load at baseline/extended targets;
10. recovery reconciliation after lost hooks/control-plane restart.

After these gates pass, changes to core ownership or deployment boundaries require an explicit ADR.
