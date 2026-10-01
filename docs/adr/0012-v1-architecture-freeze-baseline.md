# ADR 0012 — V1 Architecture Freeze Baseline

Status: **accepted**

> Consolidation note: this is the single accepted record of the V1 architecture freeze. It absorbs
> the former `0011-v1-architecture-freeze.md`, which recorded the same freeze decision from the
> initial validation run. Every unique item from that file is preserved below. Two accepted ADRs
> asserting one freeze would have been permanent dual truth, so they were merged instead.

## Decision

zero-nvr V1 architecture is frozen.

This freezes architecture ownership, canonical persistence boundaries, deployment/container
boundaries, recording/storage lifecycle, and public/internal API module boundaries.

The design-freeze runtime matrix has produced accepted evidence for every Core architecture gate. The canonical persistence boundary and public/internal module boundary are also frozen by Plan 02 and Plan 03.

Project status:

~~~text
V1 Architecture Frozen
~~~

This freezes **ownership and product contracts**, not every implementation detail or UI pixel.

## Runtime evidence

Initial freeze validation (the run that first declared the freeze):

~~~text
GitHub Actions run: 35490737812
head SHA: 20ae4741b480269bb61b69a8b4b123a46163af02
workflow conclusion: success
~~~

Latest clean full runtime matrix:

~~~text
GitHub Actions run: 35490899825

POC-01  ZLM recording / Hook indexing / control-plane independence   PASS
POC-02  fMP4 abnormal termination                                   PASS
POC-03  EVENT_ONLY pre-roll                                         PASS
POC-04  overlapping Event promotion-window extension                PASS
POC-05  wall-clock Timeline precision                               PASS
POC-06  ZLM VOD seek                                                PASS
POC-07  rclone remote restore/cache playback                        PASS
POC-08  ZLM stream sharing / source reader count                    PASS
POC-09  SQLite 8/16-camera representative mixed load                PASS
POC-10  fault/reconciliation convergence                            PASS
~~~

POC-04/06/08 share runners with POC-03/05/01 respectively.

See [POC result index](../poc-results/README.md).

## Frozen capability ownership

| Capability | V1 owner |
|---|---|
| camera RTSP pull / media routing / reconnect | ZLMediaKit |
| normal recording / segmentation | ZLMediaKit |
| default recording container mode | ZLM fMP4 |
| live protocols / VOD / snapshots | ZLMediaKit |
| canonical recording catalog | zero-nvr RecordingSegment / RecordingLocation |
| recording policy / Event reasons | zero-nvr RecordingPolicy / RecordingTrigger |
| EVENT_ONLY pre-roll | ZLM rolling short fragments in bounded tmpfs + zero-nvr promotion |
| recording wall-clock normalization | zero-nvr ZLM adapter, within proven media sessions |
| AI detection/tracking/zones | optional Frigate |
| clip/remux/transcode/frame extraction | FFmpeg / ffprobe |
| remote copy/verify/delete/restore | rclone |
| special cloud-drive gateway | optional OpenList -> WebDAV -> rclone |
| background tasks | Huey |
| notification delivery | Apprise |
| system/disaster backup repository | restic |
| camera protocol implementation | mature ONVIF / WS-Discovery libraries |
| host install/update/profile lifecycle | deploy.sh + Docker Compose |
| default product database | SQLite + WAL |
| optional scale-up database | PostgreSQL |

Ownership details:

- StorageTarget is LOCAL or RCLONE for the V1 recording/archive roles; rclone owns remote
  copy/verify/delete/restore mechanics; remote playback restores to a bounded local cache and then
  uses ZLM VOD.
- Huey, Apprise and restic own execution mechanics; zero-nvr owns the product-visible policy,
  state and orchestration around them.
- Canonical same-session recording timing uses proven continuity plus actual mux duration or a
  stronger next boundary; raw ZLM Hook timing remains source evidence.

## Frozen recording invariants

1. A camera has one normal ZLM recording pipeline for a selected RECORD stream.
2. FFmpeg is not a permanent normal recorder.
3. The product database is not in the live media write path.
4. Finalized media is represented by RecordingSegment.
5. Physical copies are represented by RecordingLocation.
6. Timeline and Gap are derived projections, not canonical tables.
7. Missed Hook/catalog work converges through idempotent reconciliation.
8. Ambiguous media is preserved/reported rather than guessed or deleted.
9. Configured segment duration is only a target; actual finalized duration is authoritative.
10. ZLM raw Hook start time is normalized only inside a proven continuous media session.
11. Source unregister/re-register always splits recording timing sessions.
12. EVENT_ONLY Events change promotion/protection windows, not recorder count.
13. EVENT_ONLY prebuffer fragments are ephemeral runtime state, not PrebufferFragment business rows.
14. Remote archive failure does not stop healthy local recording.
15. Protected/required media is never silently deleted to solve disk pressure.

## Frozen deployment baseline

Default non-AI Core:

~~~text
zero-nvr-api       # zero-nvr image
zero-nvr-worker    # same image, different command
zlmediakit         # independent media service
~~~

Target:

~~~text
2 images / 3 containers
SQLite default
no Redis requirement
no PostgreSQL requirement
no Docker socket requirement in the web/API container
~~~

Small mature CLI/library dependencies such as FFmpeg, rclone, restic, Apprise, ONVIF clients, and OIDC/auth libraries live in the zero-nvr runtime/worker image where practical rather than receiving one service container each.

Optional managed services are profile-gated and are not required for Core.

## Frozen persistence boundary

Plan 02 defines the V1 canonical table boundary.

Core rule:

> Persist durable product facts; derive runtime/projection/cache/task state whenever practical.

[ADR 0008 — Persist Product Facts, Derive Runtime State](0008-persist-product-facts-derive-runtime-state.md)
remains binding, including its promotion rule for a new canonical table.

Additional frozen persistence details:

- high-frequency telemetry/runtime projections stay out of the business database;
- the retention-oriented composite indexes measured by POC-09 are part of the V1 schema baseline;
- EVENT_ONLY has no custom packet ring, RecordingSession, RecordingIntent or PrebufferFragment business table;
- host/OS manages RAID/ZFS/Btrfs/LVM/mergerfs; zero-nvr has no StoragePool or block manager.

Adding a new canonical table after freeze requires a schema/design review. If it changes ownership or product truth, it also requires an ADR.

## Frozen API/module boundary

Plan 03 defines:

- public prefix `/api/v1`;
- internal callback prefix `/internal/hooks`;
- ISO 8601 timezone-aware public timestamps;
- camera-scope + permission authorization;
- no direct browser administration of ZLM/Frigate/rclone/OpenList;
- modular-monolith module ownership;
- thin concrete adapters;
- in-process cross-module calls;
- Huey only for asynchronous/retryable work.

Do not introduce microservice HTTP calls or a generic internal event bus for V1.

## Optional-feature gates

Core architecture freeze does **not** claim every optional integration is production-ready.

Before an optional feature is declared production-ready, run its feature-specific acceptance tests. Examples:

- Managed Frigate must consume the ZLM AI_DETECT stream without increasing source-camera reader count;
- OpenList-backed storage must pass its rclone/WebDAV archive/restore tests;
- coturn must pass remote WebRTC traversal tests where enabled;
- external PostgreSQL/OIDC/etc. require their integration tests.

These gates do not require a non-enabled Core installation to pull/start those services.

## Change-control rule after freeze

An explicit ADR plus targeted regression POC is required before changing any of the following:

- normal recording authority;
- media reconnect authority;
- default database class;
- Core container/image boundary;
- canonical RecordingSegment/RecordingLocation ownership;
- remote archive lifecycle semantics;
- EVENT_ONLY pre-roll ownership/mechanism;
- recording-time normalization model;
- deploy.sh host-mutation authority;
- canonical persisted-vs-derived boundary;
- public trust boundary (frontend -> zero-nvr only);
- adding a mandatory infrastructure dependency such as Redis/Kafka/RabbitMQ.

Implementation work may refine, without a new ADR:

- internal Python class/function layout;
- DTO field details that preserve the frozen API semantics;
- dependency versions;
- measured performance tuning;
- UI presentation;
- adapter internals;
- non-authoritative caches.

Ordinary implementation details inside those frozen contracts do not require a new ADR.

## Remaining non-architecture release validation

Architecture freeze does **not** waive implementation/release gates. Still required during
implementation:

- production Core image/static footprint measurement;
- non-AI idle RAM measurement;
- 2-camera and 4-camera small-host soak;
- frontend/browser/player integration testing;
- optional-feature smoke tests only for optional features declared production-ready;
- backup/restore/update tests against the actual production implementation;
- security/auth/RBAC integration tests.

These may reveal implementation bugs or hardware requirements. They do not reopen architecture
automatically; an architecture change still requires evidence plus an ADR.

## Consequences

Positive:

- broad implementation can begin without continuing to redesign ownership/model boundaries;
- agents/developers have one canonical architecture truth;
- POC findings are incorporated into baseline/spec/ADR/schema/API docs;
- future changes are deliberate instead of accidental architectural drift.

Trade-off:

- some implementation choices may later need an ADR if real production evidence contradicts the
  frozen design.

## Invariants

1. `PROJECT_BASELINE.md` + accepted ADRs are authoritative after this freeze.
2. All 10 design-freeze POCs have accepted evidence before declaring Frozen.
3. Implementation convenience alone does not justify changing ownership or adding infrastructure.
4. Optional integrations do not become Core dependencies without an ADR/product decision.
5. Architecture freeze is not feature-complete release status.

## Implementation phase

The next phase is implementation, not further broad architecture exploration.

Recommended order:

~~~text
Bootstrap / DB / security foundation
-> Auth / RBAC
-> Camera / ONVIF / ZLM
-> Recording catalog + reconciliation
-> Timeline / Playback
-> Events
-> Storage / rclone
-> optional Frigate AI
-> Alerts / Notifications
-> Backup / System
-> frontend integration
~~~

Runtime POCs stay in the repository as regression evidence and executable architecture tests.
