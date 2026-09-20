# zero-nvr Documentation Index

The documentation in this directory is the current design source for zero-nvr.

When documents conflict, use this precedence:

```text
PROJECT_BASELINE.md
    ↓
accepted ADRs
    ↓
accepted specs
    ↓
architecture / domain / tech-stack / deployment docs
    ↓
plans / roadmap
```

A conflict should be fixed rather than left as permanent dual truth.

## Start here

- [PROJECT_BASELINE.md](PROJECT_BASELINE.md) — highest-level non-negotiable V1 engineering baseline
- [ARCHITECTURE.md](ARCHITECTURE.md) — product boundaries, ownership, data flows, runtime topology
- [DOMAIN_MODEL.md](DOMAIN_MODEL.md) — canonical business entities and invariants
- [TECH_STACK.md](TECH_STACK.md) — implementation/component choices
- [DEPLOYMENT.md](DEPLOYMENT.md) — deploy.sh, .env, Compose Profiles, container boundaries
- [INTEGRATIONS.md](INTEGRATIONS.md) — reuse-first component/integration map
- [ROADMAP.md](ROADMAP.md) — implementation sequence and release gates
- [DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md) — engineering conventions
- [MIGRATION_FROM_V1.md](MIGRATION_FROM_V1.md) — earlier camera-recorder reference/migration policy

## Design-freeze plan

- [plans/01-design-freeze-poc.md](plans/01-design-freeze-poc.md) — required media/storage/database POCs before V1 Architecture Frozen
- [plans/00-bootstrap.md](plans/00-bootstrap.md) — platform bootstrap work
- [plans/01-zlmediakit-media-plane.md](plans/01-zlmediakit-media-plane.md) — media-plane implementation slice

Current status:

```text
V1 Design Freeze Candidate
```

## Architecture Decision Records

- [ADR 0001](adr/0001-runtime-boundaries-and-container-policy.md) — runtime/container boundary policy
- [ADR 0002](adr/0002-zlm-recording-authority.md) — ZLMediaKit owns normal recording
- [ADR 0003](adr/0003-remote-playback-restore-cache.md) — V1 remote playback restores to local cache
- [ADR 0004](adr/0004-host-managed-storage-no-product-storagepool.md) — host manages disk aggregation; no zero-nvr StoragePool
- [ADR 0005](adr/0005-deploy-sh-upgrade-authority.md) — deploy.sh is V1 deployment/upgrade authority
- [ADR 0006](adr/0006-zlm-owns-media-reconnect-runtime.md) — ZLM owns media pull/reconnect runtime
- [ADR 0007](adr/0007-recording-location-physical-copy-model.md) — RecordingLocation is the physical recording-copy model
- [ADR 0008](adr/0008-persist-product-facts-derive-runtime-state.md) — persist product facts; derive runtime/projection state

## Core product specs

### Recording and playback

- [Spec 0002 — Event Recording Lifecycle and RecordingTrigger](specs/0002-event-recording-lifecycle.md)
- [Spec 0003 — Pre-buffer Candidate](specs/0003-rolling-mp4-prebuffer.md) — **POC required; physical implementation not frozen**
- [Spec 0004 — Recording Storage Layout](specs/0004-recording-storage-layout.md)
- [Spec 0005 — Retention and Purge](specs/0005-recording-retention-and-purge.md)
- [Spec 0006 — Historical Playback Timeline](specs/0006-historical-playback-timeline.md)
- [Spec 0007 — Recording Intent Arbitration](specs/0007-recording-intent-arbitration.md)
- [Spec 0008 — Stream Loss and Reconciliation](specs/0008-stream-reconnect-and-recording-recovery.md)
- [Spec 0010 — Recording Storage Targets](specs/0010-recording-storage-pool-and-failover.md)

### Time, security, operations

- [Spec 0009 — Time and Camera Clock](specs/0009-time-and-camera-clock.md)
- [Spec 0011 — Authentication, Authorization, Audit](specs/0011-auth-authorization-and-audit.md)
- [Spec 0012 — Configuration and Secret Storage](specs/0012-config-secrets-key-management.md)
- [Spec 0013 — First Production Release Scope](specs/0013-first-production-release-scope.md)
- [Spec 0014 — Alerts and Notifications](specs/0014-alerting-notification-and-escalation.md)
- [Spec 0015 — Backup and Disaster Recovery](specs/0015-backup-disaster-recovery-and-pitr.md)
- [Spec 0016 — SQLite/PostgreSQL Portability](specs/0016-postgresql-and-sqlite-portability.md)
- [Spec 0017 — Upgrade and Rollback](specs/0017-upgrade-migration-and-rollback.md)

### Camera, live, AI, integrations

- [Spec 0018 — Camera Onboarding](specs/0018-camera-onboarding-discovery-and-stream-selection.md)
- [Spec 0019 — Device Runtime Lifecycle](specs/0019-device-runtime-lifecycle-and-reconfiguration.md)
- [Spec 0020 — Live View / Media Session / Compatibility](specs/0020-live-view-media-session-and-talk.md)
- [Spec 0021 — Detection Providers / AI Events / Frigate](specs/0021-detection-providers-ai-events-and-fusion.md)
- [Home Assistant integration spec](specs/0002-home-assistant-integration.md)

## Important interpretation rules

- Mature components are preferred over custom infrastructure.
- ZLMediaKit owns media transport, normal recording, and VOD.
- Frigate is optional AI, not recording authority.
- FFmpeg is an on-demand derived-media/recovery tool, not the permanent recorder.
- rclone/restic/Apprise and similar small tools/libraries are integrated into the zero-nvr/worker image where practical.
- SQLite is the default production database.
- V1 Core target is 2 images / 3 containers.
- Optional components are not pulled or started unless enabled.
- deploy.sh is the V1 host-mutation/deployment interface.
- V1 completeness means the supported lifecycle is complete, not that every possible protocol/integration ships in V1.
- Any old spec wording that conflicts with PROJECT_BASELINE or an accepted ADR must be corrected before implementation.

## Before implementation of a phase

For each phase:

1. confirm it does not conflict with PROJECT_BASELINE/ADRs;
2. complete any required POC;
3. freeze the relevant data/API contract;
4. define tests and acceptance criteria;
5. implement incrementally;
6. update the documentation when the implementation proves an assumption wrong.
