# Technology Stack Baseline

Status: **recommended defaults, subject to implementation validation**

## Control plane

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- SQLite (default production database)
- PostgreSQL (optional enhanced production database)

Responsibilities:

- domain APIs;
- orchestration;
- policy;
- authorization;
- adapters;
- metadata persistence.

### Frontend

- Vue 3
- TypeScript
- Vite
- Element Plus initially unless a later UI-system decision replaces it

Responsibilities:

- Device Center;
- Live Monitor;
- Recording Timeline;
- Events;
- Alerts;
- Storage;
- System Health.

## Media plane

### ZLMediaKit

Default media engine for:

- RTSP ingest/proxy;
- stream reconnect;
- WebRTC;
- HTTP-fMP4;
- HLS;
- media runtime state;
- media webhooks.

### FFmpeg / ffprobe

Integrated into the zero-nvr/worker runtime image as an on-demand media toolchain for:

- export and clipping;
- concat/remux/transcode;
- historical frame extraction;
- media inspection;
- repair/compatibility tasks.

FFmpeg is **not** the normal permanent per-camera recorder. Normal continuous/scheduled recording is owned by ZLMediaKit's recorder.

## Device plane

### ONVIF

Use a maintained ONVIF client library for SOAP/WSDL/WS-Security.

zero-nvr implements:

- WS-Discovery/onboarding orchestration through the maintained library;
- stable device/channel identity mapping;
- canonical Device/Camera/SourceMediaProfile/capability DTOs;
- source-profile to recording/live/preview/detection role selection;
- event normalization;
- business policy.

zero-nvr does not implement a general ONVIF SOAP stack.

### HIK

Use the official/vendor SDK behind an isolated bridge process.

Prefer standard ONVIF onboarding when it provides the required capabilities; HIK may supplement the same canonical Device with vendor-only events/control rather than creating a duplicate device.

### Device runtime reconciliation

The FastAPI/control-plane side owns a thin RuntimeReconciler that maps durable Device/Camera configuration into adapter operations.

ZLMediaKit remains responsible for media transport, pull/reconnect runtime, and recorder execution. zero-nvr must not duplicate those responsibilities with a packet monitor or RTSP reconnect state machine.

Runtime-relevant configuration may use revisions/generations so stale adapter callbacks cannot overwrite newer product state. External network/media calls occur outside short database transactions.

See [Spec 0019](specs/0019-device-runtime-lifecycle-and-reconfiguration.md).

### GB28181

Optional future integration; it does not block V1.

If enabled later:

- WVP provides SIP/device protocol handling;
- ZLMediaKit remains the media layer;
- zero-nvr integrates through an adapter rather than implementing GB28181 itself.

## Event / AI plane

Priority:

1. camera-native events;
2. vendor-native smart events;
3. optional external AI provider;
4. local lightweight detection where appropriate.

First-production-release AI provider integration:

- Frigate via integration boundary, not as the zero-nvr system of record.

AI remains optional to enable, but the integration is implemented before the first production release.

Event bus/integration protocol may use MQTT where it meaningfully decouples external providers. MQTT is not mandatory for internal business calls.

## Integration plane

Home Assistant is a first-class optional integration target.

Loading model:

```text
Core zero-nvr
  → no HA dependency
  → no MQTT dependency

Enable HA REST integration
  → authenticated external-trigger API only

Enable HA deep integration
  → optional MQTT broker
  → MQTT Discovery/state/commands

HA Custom Integration
  → ships in the first production release and consumes the stable zero-nvr API
```

The core deployment must remain fully functional when Home Assistant and MQTT are absent.

Home Assistant automations should send canonical external events/recording triggers. They must not directly control FFmpeg subprocesses or ZLMediaKit internals.

## Notification plane

First-production-release notification capabilities:

- native SMTP/email backend;
- Apprise generic provider backend;
- webhook delivery;
- integration actions such as Home Assistant where configured.

SMTP is also used for self-service password reset, security/account notifications, and system-health notification.

SMTP credentials are SecretStore-backed. Delivery uses the durable notification worker with retry/result tracking.

## Storage plane

First-class product concepts:

- local hot recording storage;
- remote archive through rclone-supported backends.

rclone is integrated as a worker CLI tool rather than a mandatory sidecar service. OpenList is optional and is used primarily as an aggregation/protocol adapter for storage providers that are awkward to access directly with rclone.

Archive state is product-owned and follows copy -> verify -> mark remote available -> retention may delete local. Upload success alone is insufficient for local purge eligibility.

## Database

### Production

Two supported production modes:

- SQLite — default lightweight single-host mode;
- PostgreSQL — optional enhanced mode for higher write concurrency/larger deployments.

SQLite production uses WAL mode, short transactions, bounded busy retry, controlled checkpointing, and a local filesystem.

PostgreSQL remains available as bundled or external service.

Both modes provide the same product capabilities; backend-specific locking, queue coordination, indexing, and backup behavior stay behind persistence/database capabilities.

### Development/testing and portability

CI includes shared domain tests plus production integration tests for both SQLite and PostgreSQL.

A separate versioned SQLite portable/offline index format remains available for metadata export/import, detached-media inspection, recovery analysis, and migration tooling.

See [Spec 0016](specs/0016-postgresql-and-sqlite-portability.md).

## Jobs

Huey is the default background-task and scheduling implementation.

Deployment rules:

- SQLite deployments use Huey's SQLite-backed mode;
- PostgreSQL deployments may use the PostgreSQL-backed mode;
- Redis/RabbitMQ/Celery are not mandatory infrastructure;
- background work runs in `zero-nvr-worker`, which uses the same image as the API container.

Job categories include:

- archive/remote transfer;
- export and derived media;
- notification;
- storage verification;
- retention/cleanup;
- backup;
- reconciliation/index repair.

Long-lived media runtime and normal camera recording remain ZLMediaKit responsibilities rather than queue jobs.


## Security / secrets

Use mature libraries rather than custom cryptography:

- Argon2id through a maintained password library for local password hashing;
- Python `cryptography` or equivalent for authenticated encryption of recoverable SecretRecords;
- Fernet/MultiFernet or a similarly small authenticated-encryption/key-rotation approach is preferred for V1 simplicity;
- stable master/keyring bootstrap through `ZERO_NVR_SECRET_KEY` or protected `*_FILE`;
- one-way hashes for Personal API Tokens and password-reset tokens.

V1 does not require per-record DEK/KEK envelope encryption, Vault, or KMS. Those may be added later behind SecretStore if a deployment class requires them.

Production deployments should keep the master key outside the product database and preserve it through the RecoveryKit process.

See [Spec 0012](specs/0012-config-secrets-key-management.md).

## Observability

Initial:

- structured application logs;
- health/readiness endpoints;
- runtime state APIs.

Optional observability extensions:

- Prometheus-compatible metrics;
- OpenTelemetry tracing where useful;
- Grafana when an operator wants long-term dashboards.

They are not required for a complete lightweight V1. zero-nvr itself provides structured logs, health/readiness, and product health state.

## Deployment

Primary deployment model:

- Docker Compose on Linux;
- `deploy.sh + .env + Docker Compose Profiles`;
- Core target: 2 images / 3 containers (zero-nvr API, zero-nvr worker, ZLMediaKit);
- optional services are not pulled or started unless enabled;
- the web application does not require direct Docker socket control.

Small CLI/library dependencies such as FFmpeg, rclone, restic, Apprise, ONVIF libraries, and Authlib are integrated into the zero-nvr runtime/worker image where practical.

Do not make Kubernetes a V1 prerequisite.

## Implementation choices still requiring validation

Architecture ownership is now fixed: ZLM owns normal recording, Huey owns background jobs, and V1 remote-only playback restores media into a bounded local cache before ZLM VOD.

Remaining design-freeze validation is intentionally narrow:

- whether ZLM fMP4 recording becomes the default recording container;
- the exact ZLM-native mechanism for ~10s EVENT_ONLY pre-roll;
- live-player protocol priority under browser/codec combinations;
- timeline/VOD seek precision;
- remote restore/prefetch performance.

Multi-node media topology is outside the V1 freeze gate.


## Backup and recovery

System/disaster backup is separate from recording archive.

Default first-release path:

- SQLite Online Backup API for consistent SQLite snapshots;
- `pg_dump` for PostgreSQL logical backup where PostgreSQL is used;
- restic for encrypted/versioned backup repository storage, deduplication, retention, and integrity checking;
- RecoveryKit/master-secret preservation as required by SecretStore.

Recording media is normally protected by recording archive/retention policy rather than copied into every system backup.

Disposable data such as playback cache, export cache, thumbnails, rclone cache, and current in-memory health state is excluded.

Advanced PITR engines may be supported later/optionally, but are not mandatory to keep the lightweight V1 deployment complete.

See [Project Baseline](PROJECT_BASELINE.md).


## Upgrade and migration

V1 upgrades are driven by `deploy.sh` rather than an in-app Docker orchestrator.

Core primitives:

- Alembic for schema coordination across SQLite and PostgreSQL;
- SQLite Online Backup + restic safety point for incompatible SQLite changes;
- pg_dump + restic safety point for PostgreSQL changes;
- version/digest-pinned releases rather than mutable `latest`;
- startup schema/version compatibility gate;
- separate controlled SQLite <-> PostgreSQL migration.

A heavyweight persisted UpgradePlan/automatic scheduled self-update system is not a V1 requirement.

See [Spec 0017](specs/0017-upgrade-migration-and-rollback.md).


## Live delivery and transcoding

First-production-release live stack:

- ZLMediaKit for WebRTC, fMP4/HLS delivery, live protocol conversion, and media-session runtime;
- coturn for STUN/TURN traversal;
- FFmpeg for on-demand compatibility transcode when no browser-compatible source profile exists;
- browser capability probing rather than user-agent-only codec assumptions.

Default transport preference:

```text
WebRTC -> fMP4 -> HLS
```

Grid/focused quality primarily switches between `live_preview` and `live_main`. Transcoding is compatibility fallback rather than the default ingest path.

Live transcode can use detected platform acceleration such as VAAPI/QSV/NVENC/VideoToolbox when available; recording correctness has priority over optional live-transcode demand.

TURN credentials are short-lived and derived/issued for authenticated MediaSessions rather than exposing permanent coturn credentials.

See [Spec 0020](specs/0020-live-view-media-session-and-talk.md).


## Detection and AI providers

V1 event architecture stays narrow:

- mature ONVIF library event service for camera-native events;
- Frigate as the primary optional AI provider;
- vendor event bridge only when ONVIF cannot expose the required capability;
- one canonical zero-nvr Event model.

Frigate integration may use MQTT and/or its supported HTTP API according to the deployed version/integration path. Frigate owns detection/tracking/zones; zero-nvr stores only the product fields needed for timeline, search, alerts, recording policy, and permissions.

Provider source identity is preserved so repeated new/update/end messages UPSERT the same Event.

V1 does not require DetectionObservation sampling tables, EventFusionGroup, or a local custom detector engine.

See [Spec 0021](specs/0021-detection-providers-ai-events-and-fusion.md).
