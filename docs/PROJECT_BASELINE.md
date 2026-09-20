# zero-nvr Project Baseline

Status: **V1 Architecture Frozen**

This file is the highest-level engineering baseline for zero-nvr. When another document conflicts with this file, this file wins until the conflict is resolved by an explicit architecture decision.

## Product target

zero-nvr is a lightweight but complete self-hosted NVR for home, personal, NAS/home-server, small-office, and small-to-medium camera deployments.

The first stable release must be usable end-to-end rather than a demo/MVP. Completeness means that the normal lifecycle has no functional dead end: install, initialize, add cameras, record, play back, inspect events, retain/archive, notify, back up, restore, and upgrade.

## Core engineering principles

1. **Mature components first.** Reuse proven media, protocol, transfer, notification, backup, and identity libraries/tools instead of reimplementing them.
2. **One clear owner per capability.**
   - ZLMediaKit: camera ingest, media routing, live delivery, fMP4 recording by default, VOD.
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
5. **SQLite is the default production database.** PostgreSQL is optional for larger deployments; user-facing features remain equivalent. POC-09 validated SQLite WAL under the representative 8-camera baseline and 16-camera extended mixed workload on the tested 4-CPU runner with zero final lock failures. The optimized retention plan also passed the local <500ms p95 gate at about 12.11ms / 11.31ms using the frozen camera/end-time + segment/location composite indexes.
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
Camera -> ZLMediaKit -> ZLM Recorder (fMP4 default) -> local hot storage
                                      -> on_record_mp4 -> RecordingCatalog
```

FFmpeg is reserved for derived work such as export, clip/concat/remux, compatibility transcode, historical frame extraction, repair, and fallback inspection.

Recording media files and the product catalog are **eventually consistent**. A missed hook must be recoverable through reconciliation; the database must not be placed in the media hot path.

This model is validated by [POC-10 — Recovery Reconciliation](poc-results/10-reconciliation.md): control-plane restart, temporary SQLite write unavailability, lost hooks, stale catalog rows, provable orphan recovery, ambiguous orphan preservation, and reconciliation-process restart all converged idempotently without deleting valid media.

Accepted reconciliation rules:

~~~text
valid unindexed media + provable identity
  -> recover RecordingSegment / RecordingLocation

catalogued AVAILABLE copy missing from storage
  -> mark MISSING / explain

ambiguous unindexed media
  -> preserve + surface diagnostically
  -> never guess identity or auto-delete

second reconciliation after convergence
  -> zero additional mutations
~~~

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

### EVENT_ONLY pre-roll baseline

The V1 EVENT_ONLY pre-roll mechanism is **accepted**, validated by [POC-03](poc-results/03-event-preroll.md) and [POC-04](poc-results/04-multi-event-extension.md).

~~~text
Camera
  -> one normal ZLM recorder
  -> short finalized fragments in bounded tmpfs
  -> on_record_mp4
  -> RecordingTrigger/Event overlap selects whole fragments
  -> copy to destination *.partial
  -> verify
  -> atomic publish
  -> RecordingSegment + RecordingLocation
~~~

Accepted behavior:

- default product target remains about 10 seconds pre-roll and 10 seconds post-roll;
- Event arrival/updates change a derived promotion/protection window, not recorder lifecycle;
- overlapping Events remain independent Event/RecordingTrigger facts;
- one fragment serving several Events is promoted once;
- whole-fragment extra coverage is acceptable; exact trimming is an Export concern;
- FastAPI restart reconstructs required coverage from durable RecordingTrigger facts plus tmpfs scan;
- no PrebufferFragment/RecordingSession table is required;
- tmpfs must be explicitly bounded and monitored;
- H.264 and H.265/HEVC passed the design-freeze matrix.

zero-nvr still must not implement a custom H.264/H.265 packet ring buffer or a second permanent event recorder.

The accepted EVENT_ONLY rolling recorder therefore uses the same V1 default fMP4 mode as normal recording.

## Recording format

The V1 default ZLMediaKit recording mode is **fMP4** (`record.enableFmp4=1`), validated by [POC-02 — fMP4 Abnormal Termination Recovery](poc-results/02-fmp4-crash.md).

Under the same SIGKILL scenario:

- ordinary in-progress MP4 failed ffprobe/decode/remux because its `moov` metadata was not finalized;
- the interrupted fMP4 remained inspectable and decodable;
- FFmpeg stream-copy/remux succeeded;
- unchanged surviving fMP4 was playable through ZLM HTTP/RTSP VOD after restart;
- normally finalized fMP4 also passed the intended ZLM playback path.

No repair daemon is required.

Playback/browser compatibility remains resolved through ZLM/player descriptors rather than assuming every browser consumes the raw recording file directly.

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

This baseline path is validated by [POC-07 — Remote Restore Playback](poc-results/07-remote-restore.md): interrupted restore/retry, bounded byte-size cache eviction, ZLM VOD playback, next-segment prefetch, and isolation of remote failure from local recording all passed.

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

## Architecture-freeze status

**V1 Architecture Frozen.**

The freeze is backed by the successful final design-validation workflow:

~~~text
GitHub Actions run: 35490737812
head SHA: 20ae4741b480269bb61b69a8b4b123a46163af02
conclusion: success
~~~

All 10 design-freeze POCs have accepted runtime results:

- POC-01 — ZLM recording / Hook indexing / control-plane restart convergence;
- POC-02 — fMP4 abnormal-termination recovery and MP4 comparison;
- POC-03 — EVENT_ONLY pre-roll;
- POC-04 — overlapping Event promotion-window extension;
- POC-05 — wall-clock Timeline precision / real source-loss Gap;
- POC-06 — ZLM VOD seek;
- POC-07 — remote restore -> bounded cache -> ZLM playback;
- POC-08 — ZLM stream sharing / source-camera connection count;
- POC-09 — SQLite 8/16-camera mixed load + retention-query plan;
- POC-10 — fault/reconciliation convergence.

Persistence boundaries are frozen by Plan 02; public/internal API and module ownership are frozen by Plan 03.

After this point, implementation may refine internals, versions, DTO details, UI, and measured performance without reopening architecture. Changes to core ownership, mandatory runtime services/containers, recording/storage lifecycle, default database class, persistence boundary, or frontend trust boundary require an explicit ADR.

See [ADR 0011 — V1 Architecture Freeze](adr/0011-v1-architecture-freeze.md) and [POC result index](poc-results/README.md).
