# ADR 0011 — V1 Architecture Freeze

Status: **accepted**

## Decision

zero-nvr V1 architecture is frozen as of the successful design-freeze validation matrix:

~~~text
GitHub Actions run: 35490737812
head SHA: 20ae4741b480269bb61b69a8b4b123a46163af02
workflow conclusion: success
~~~

Project architecture status becomes:

~~~text
V1 Architecture Frozen
~~~

This freezes architecture ownership, canonical persistence boundaries, deployment/container boundaries, recording/storage lifecycle, and public/internal API module boundaries.

It does **not** mean implementation is complete or every dependency version/API response shape is immutable.

## Freeze gates

All numbered design-freeze POCs have accepted runtime results:

1. ZLM normal recording / Hook indexing / API restart convergence — PASS.
2. fMP4 abnormal-termination comparison — PASS; fMP4 selected.
3. EVENT_ONLY pre-roll — PASS.
4. overlapping Event promotion-window extension — PASS.
5. wall-clock Timeline / real Gap precision — PASS.
6. ZLM VOD seek — PASS.
7. rclone remote restore -> bounded cache -> ZLM playback — PASS.
8. ZLM source-stream sharing / source connection count — PASS.
9. SQLite 8/16-camera representative mixed load + optimized retention query — PASS.
10. fault/reconciliation convergence — PASS.

Persistence is frozen by [Plan 02 — V1 Schema Freeze](../plans/02-v1-schema-freeze.md).

API/module ownership is frozen by [Plan 03 — V1 API and Module Boundary Freeze](../plans/03-v1-api-module-freeze.md).

Measured POC details live under [docs/poc-results](../poc-results/README.md).

## Frozen ownership boundaries

### Media

- ZLMediaKit owns camera pull, reconnect, media routing, normal recorder, segmentation, VOD, snapshots and live protocol delivery.
- Managed normal recording defaults to fMP4.
- FFmpeg/ffprobe is derived-media/recovery tooling, never the permanent normal recorder.
- Frontend never directly administers ZLM.

### EVENT_ONLY

- one continuously-running normal ZLM recorder writes short fMP4 fragments into bounded tmpfs;
- durable RecordingTrigger facts define required pre/post-roll windows;
- whole finalized overlapping fragments are verified and promoted once;
- overlapping Events extend a derived promotion window, not recorder count;
- no custom packet ring, RecordingSession, RecordingIntent or PrebufferFragment business table.

### Recording timeline

- RecordingSegment + RecordingLocation are canonical recording/media-copy facts;
- raw ZLM Hook timing remains source evidence;
- canonical same-session timing uses proven continuity plus actual mux duration / stronger next boundary;
- ZLM unregister/re-register splits timing sessions;
- Timeline and Gap are projections, never canonical tables.

### Storage

- StorageTarget is LOCAL or RCLONE for V1 recording/archive roles;
- rclone owns remote copy/verify/delete/restore mechanics;
- remote playback restores to a bounded local cache and then uses ZLM VOD;
- OpenList is optional only as a special-drive WebDAV gateway;
- host/OS manages RAID/ZFS/Btrfs/LVM/mergerfs; zero-nvr has no StoragePool/block manager.

### Database

- SQLite + WAL is the default production database;
- PostgreSQL is optional scale-up/external/bundled deployment, not the definition of production;
- no Redis/Celery/RabbitMQ requirement;
- high-frequency telemetry/runtime projections stay out of the business database;
- the retention-oriented composite indexes measured by POC-09 are part of the V1 schema baseline.

### Jobs / notifications / backup

- Huey owns background execution/retry;
- Apprise owns outbound notification delivery where supported;
- restic owns system/disaster backup repository mechanics;
- zero-nvr owns product-visible policy/state/orchestration.

### Deployment

- default non-AI Core target remains 2 unique images / 3 containers;
- API and worker use the same zero-nvr image;
- optional independently-running services are pulled/started only when enabled;
- deploy.sh + .env + Compose Profiles is the host deployment authority;
- browser/API container does not receive unrestricted Docker-socket authority.

## Frozen persistence principle

ADR 0008 remains binding:

> Persist durable product facts; derive runtime/projection/task state whenever practical.

A new canonical V1 table requires the ADR 0008 promotion rule and schema review.

## Change control after freeze

Implementation work may refine:

- internal Python class/function layout;
- DTO field details that preserve the frozen API semantics;
- dependency versions;
- measured performance tuning;
- UI presentation;
- adapter internals;
- non-authoritative caches.

An explicit ADR is required before changing a frozen architectural boundary, including:

- normal recording authority;
- default database class;
- Core mandatory container/service set;
- canonical recording-copy model;
- remote archive/playback ownership;
- EVENT_ONLY physical strategy;
- persistence-vs-derived-state boundary;
- public trust boundary (frontend -> zero-nvr only);
- deployment authority;
- adding a mandatory infrastructure dependency such as Redis/Kafka/RabbitMQ.

## Remaining non-architecture release validation

Architecture freeze does not waive implementation/release gates.

Still required during implementation include:

- production Core image/static footprint measurement;
- non-AI idle RAM measurement;
- 2-camera and 4-camera small-host soak;
- frontend/browser/player integration testing;
- optional-feature smoke tests only for optional features declared production-ready;
- backup/restore/update tests against the actual production implementation;
- security/auth/RBAC integration tests.

These may reveal implementation bugs or hardware requirements. They do not reopen architecture automatically; an architecture change requires evidence plus an ADR.

## Consequences

Positive:

- broad implementation can begin without continuing to redesign ownership/model boundaries;
- agents/developers have one canonical architecture truth;
- POC findings are now incorporated into baseline/spec/ADR/schema/API docs;
- future changes are deliberate instead of accidental architectural drift.

Trade-off:

- some implementation choices may later need an ADR if real production evidence contradicts the frozen design.

## Invariants

1. `PROJECT_BASELINE.md` + accepted ADRs are authoritative after this freeze.
2. All 10 design-freeze POCs have accepted evidence before declaring Frozen.
3. Implementation convenience alone does not justify changing ownership or adding infrastructure.
4. Optional integrations do not become Core dependencies without an ADR/product decision.
5. Architecture freeze is not feature-complete release status.
