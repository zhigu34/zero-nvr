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

Retained for:

- reliable recording backend during early V2;
- export;
- remux/transcode;
- media inspection;
- repair/compatibility tasks.

The goal is not to remove FFmpeg. The goal is to stop using FastAPI as a media server.

## Device plane

### ONVIF

Use a maintained ONVIF client library for SOAP/WSDL/WS-Security.

zero-nvr implements:

- adapter mapping;
- canonical device/profile/capability DTOs;
- event normalization;
- business policy.

zero-nvr does not implement a general ONVIF SOAP stack.

### HIK

Use the official/vendor SDK behind an isolated bridge process.

### GB28181

First-production-release integration, optional to enable at deployment:

- WVP for SIP/device protocol;
- ZLMediaKit for media.

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

First-class:

- Local
- S3-compatible

Generic integrations:

- rclone
- OpenList

Storage adapters must expose verification semantics; upload success alone is insufficient for local purge eligibility.

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

Worker implementation is intentionally not locked yet.

Candidate patterns:

- DB-backed durable job queue for a small deployment;
- Redis-backed worker when concurrency/throughput justifies it.

Job categories:

- upload;
- export;
- thumbnail/snapshot;
- notification;
- storage verification;
- retention;
- background media processing.

Long-running camera/media runtimes are not ordinary queue jobs.


## Security / secrets

Initial cryptographic direction:

- Argon2id for local password hashing;
- authenticated encryption for recoverable managed secrets;
- AES-256-GCM as the initial envelope-encryption primitive;
- per-SecretRecord random DEK;
- external/versioned KEK keyring supplied through Docker secrets/protected files or an equivalent bootstrap provider;
- opaque/hash-stored authentication tokens where reversible secret recovery is unnecessary.

Python implementation should use a maintained cryptographic library rather than custom cryptography.

SecretStore remains an application abstraction so a later Vault/KMS/secret-manager backend can replace the initial encrypted-database implementation without changing Camera/Storage/Integration domain contracts.

Production deployments should prefer Docker secret files or `*_FILE` bootstrap configuration for the PostgreSQL password and SecretStore key material rather than plaintext environment variables.

See [Spec 0012](specs/0012-config-secrets-key-management.md).

## Observability

Initial:

- structured application logs;
- health/readiness endpoints;
- runtime state APIs.

First production release:

- Prometheus-compatible metrics;
- OpenTelemetry tracing where useful;
- Grafana optional to deploy.

## Deployment

Initial:

- Docker Compose on Linux.

Do not make Kubernetes a V2 prerequisite.

## Implementation choices still requiring validation

These are engineering choices to settle during the first production release, not post-release feature deferrals:

- final recording container/segment format;
- exact task queue implementation;
- exact live-player protocol priority under all browsers;
- ZLM-native recorder vs FFmpeg recorder;
- cache implementation for remote playback;
- multi-node media topology.


## Backup and recovery

First-production-release database backup engines:

- SQLite Online Backup API for consistent scheduled snapshots;
- Litestream for continuous SQLite remote replication and point-in-time restore on compatible targets;
- pgBackRest for PostgreSQL full/differential/incremental backup, WAL archiving, restore, and PITR.

Repository support is capability-based. Generic StorageBackends such as S3/rclone/OpenList/local can receive verified SQLite/system snapshots. Continuous SQLite replication and PostgreSQL PITR are exposed only when the selected backend is compatible.

zero-nvr owns BackupPolicy, manifests, RecoveryKit, restore orchestration, health, audit, and UI rather than reimplementing database backup protocols.

See [Spec 0015](specs/0015-backup-disaster-recovery-and-pitr.md).

## Upgrade and migration

First-production-release upgrade primitives:

- Alembic for schema coordination across SQLite and PostgreSQL;
- explicit migration compatibility classes and expand/contract preference;
- SQLite Online Backup safety point before schema-rebuild/incompatible changes;
- pgBackRest safety point for PostgreSQL incompatible migrations;
- version/digest-pinned container/package releases rather than mutable latest tags;
- persisted UpgradePlan/UpgradeHistory and startup schema-compatibility gate;
- separate guided DatabaseMigrationPlan for SQLite ↔ PostgreSQL cutover.

Large backfills are durable resumable DataMigrationJobs rather than opaque startup work.

See [Spec 0017](specs/0017-upgrade-migration-and-rollback.md).
