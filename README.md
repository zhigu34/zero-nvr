# zero-nvr

**zero-nvr** is a custom NVR management platform built around a simple rule:

> Mature components handle protocols and media. zero-nvr owns the NVR product, control plane, and domain model.

The project is a clean V2 rewrite of the earlier camera-recorder experiment. It is not a line-by-line port and does not inherit V1 implementation constraints.

## Product scope

zero-nvr is intended to unify:

- camera and connection management;
- live preview and media sessions;
- continuous and event recording;
- native camera events and optional AI detection;
- alert rules and notifications;
- local storage and retention;
- cloud upload and verification;
- historical timeline and playback;
- device/runtime/storage health;
- permissions, audit and integrations.

## Architecture direction

```text
Vue 3
  |
FastAPI Control Plane
  |
  +-- Device Plane ------ ONVIF library / vendor bridges / optional WVP
  |
  +-- Media Plane ------- ZLMediaKit / FFmpeg
  |
  +-- Event Plane ------- native camera events / optional AI providers
  |
  +-- Job Plane --------- upload / export / notification / retention
  |
  +-- Storage Plane ----- local / S3 / rclone / OpenList
  |
SQLite (default) / PostgreSQL (optional)
```

The authoritative business model remains inside zero-nvr. External components are adapters, not competing sources of truth.

## Reuse-first rule

Before implementing protocol or infrastructure code, ask:

1. Is there a mature existing implementation?
2. Can it be wrapped behind a zero-nvr adapter?
3. Does zero-nvr truly gain product value by owning this implementation?

Default decisions:

- media proxy / WebRTC / HLS / fMP4: **ZLMediaKit**;
- recording/transcode/export primitives: **FFmpeg / ffprobe**;
- ONVIF SOAP/WSDL/WS-Security: **mature ONVIF library**;
- HIK private protocol: **vendor SDK through an isolated bridge**;
- GB28181: **optional WVP + ZLMediaKit integration**;
- notifications: **Apprise or adapter-backed providers**;
- generic cloud storage: **S3 / rclone / OpenList adapters**;
- AI detection: **optional provider integration such as Frigate**, not a second NVR authority.

## Repository layout

```text
backend/       FastAPI control plane and domain services
frontend/      Vue 3 management UI
deploy/        deployment and infrastructure definitions
docs/          architecture, domain and implementation plans
```

The directories are intentionally lightweight during initialization. Implementation details will be introduced phase by phase.

## Current status

Architecture baseline is being finalized for the first production release.

The first production release is intentionally complete rather than MVP-scoped: engineering phases are implementation order, and known product-grade capabilities are expected to ship before the first stable release.

Start with:

- [Architecture](docs/ARCHITECTURE.md)
- [Technology Stack](docs/TECH_STACK.md)
- [Domain Model](docs/DOMAIN_MODEL.md)
- [Integrations](docs/INTEGRATIONS.md)
- [Roadmap](docs/ROADMAP.md)
- [V2 Platform Spec](docs/specs/0001-platform-architecture.md)
- [Event Recording Lifecycle](docs/specs/0002-event-recording-lifecycle.md)
- [Rolling MP4 Pre-buffer](docs/specs/0003-rolling-mp4-prebuffer.md)
- [Recording Storage Layout](docs/specs/0004-recording-storage-layout.md)
- [Recording Retention and Safe Purge](docs/specs/0005-recording-retention-and-purge.md)
- [Historical Playback Timeline](docs/specs/0006-historical-playback-timeline.md)
- [Recording Intent Arbitration](docs/specs/0007-recording-intent-arbitration.md)
- [Stream Reconnect and Recording Recovery](docs/specs/0008-stream-reconnect-and-recording-recovery.md)
- [Canonical Time and Camera Clock](docs/specs/0009-time-and-camera-clock.md)
- [Recording Storage Pool and Failover](docs/specs/0010-recording-storage-pool-and-failover.md)
- [Authentication, Authorization, and Audit](docs/specs/0011-auth-authorization-and-audit.md)
- [Configuration, Secrets, and Key Management](docs/specs/0012-config-secrets-key-management.md)
- [First Production Release Scope](docs/specs/0013-first-production-release-scope.md)
- [Alerting, Notification, and Escalation](docs/specs/0014-alerting-notification-and-escalation.md)
- [Backup, Disaster Recovery, and PITR](docs/specs/0015-backup-disaster-recovery-and-pitr.md)
- [SQLite and PostgreSQL Production Modes](docs/specs/0016-postgresql-and-sqlite-portability.md)
- [Upgrade, Migration, and Rollback](docs/specs/0017-upgrade-migration-and-rollback.md)
- [Camera Onboarding, Discovery, and Stream Selection](docs/specs/0018-camera-onboarding-discovery-and-stream-selection.md)
- [Device Runtime Lifecycle and Reconfiguration](docs/specs/0019-device-runtime-lifecycle-and-reconfiguration.md)
- [Development Guidelines](docs/DEVELOPMENT_GUIDELINES.md)
- [Bootstrap Plan](docs/plans/00-bootstrap.md)

## V1 relationship

The previous project is treated as a behavior/reference source, not as the V2 codebase.

V2 migration principles:

- preserve useful product lessons;
- preserve external data only when an explicit migration is designed;
- do not copy legacy protocol implementations merely because they already exist;
- keep adapters and domain contracts clean from the start;
- migrate capabilities incrementally rather than recreating V1 internals.
