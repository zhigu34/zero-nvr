# Spec 0013 — First Production Release Scope and Completeness Policy

Status: **accepted**

## Goal

Define what "complete first release" means for zero-nvr.

Core rule:

> V1 must be a complete, long-term usable NVR for its supported deployment class. Completeness is an end-to-end product lifecycle, not a requirement to ship every surveillance protocol, vendor integration, AI feature, storage engine, or observability platform.

See [Project Baseline](../PROJECT_BASELINE.md).

## Target deployment class

V1 is optimized for:

- home/personal NVR;
- NAS/home-server;
- small office;
- small-to-medium camera deployments;
- single-host deployment by default;
- SQLite by default;
- optional PostgreSQL for larger deployments.

Baseline performance target: 8 cameras.

Extended validation target: 16 cameras.

## Complete lifecycle requirement

A normal user must be able to complete this lifecycle without hitting a designed-in dead end:

```text
install
-> first-run initialization
-> create/recover administrator
-> add cameras
-> live view
-> configure recording
-> record reliably
-> timeline / playback / gaps
-> inspect events
-> protect/export footage
-> manage retention
-> archive remotely
-> restore/play remote-only footage
-> receive alerts/notifications
-> inspect system health
-> back up configuration/database/secrets
-> restore on a clean host
-> upgrade safely
```

This is the primary meaning of "complete V1".

## Required V1 product areas

### Deployment and initialization

- `deploy.sh + .env + Docker Compose Profiles`;
- optional services are not pulled/started unless enabled;
- first-run administrator creation;
- timezone and host time/NTP health;
- recording storage selection;
- camera onboarding;
- recording-policy initialization;
- optional feature/integration setup.

### Camera and device management

- ONVIF discovery using a mature WS-Discovery/ONVIF library;
- manual ONVIF;
- manual RTSP fallback;
- multi-stream/profile discovery where available;
- explicit stream-purpose binding;
- camera enable/disable;
- capability display;
- PTZ where standard ONVIF capability exists;
- camera time/NTP configuration where supported;
- stable identity handling sufficient to survive ordinary DHCP/address changes.

Vendor-private adapters are enhancements, not the foundation of standard onboarding.

### Media and live view

- ZLMediaKit as the only normal camera-facing media bus;
- live preview;
- multi-camera layouts;
- high/low stream selection;
- browser-compatible delivery through ZLM-supported protocols/player adapters;
- live snapshot;
- audio where the camera/browser path supports it.

Advanced two-way talk/vendor backchannel support should not delay the entire release when unsupported by the core device path.

### Recording

- continuous recording;
- schedule recording;
- EVENT_ONLY recording;
- disabled mode;
- manual/protection workflows as defined by product UI;
- ZLM as normal recording authority;
- actual-time RecordingSegment indexing;
- `on_record_mp4` normal catalog path;
- reconciliation after lost hooks/control-plane restart;
- no permanent per-camera FFmpeg recorder;
- RecordingTrigger with type/source/state/reason/correlation_id/pre/post-roll/planned window;
- overlapping triggers extend one logical recording interval rather than starting duplicate recorders.

EVENT_ONLY ~10 second pre-roll is accepted for V1 using one continuously-running ZLM short-fragment recorder in bounded tmpfs plus whole-fragment promotion from RecordingTrigger windows. POC-03/04 validated H.264/H.265 coverage, overlapping triggers, bounded tmpfs, and restart reconstruction without a custom H.264/H.265 packet ring buffer.

### Historical playback

- true wall-clock timeline;
- merged recording ranges;
- real gaps;
- Event markers;
- wall-clock -> segment/media-offset resolution;
- ZLM VOD/seek path;
- local playback;
- remote-only restore -> bounded local cache -> ZLM playback;
- export using FFmpeg-derived jobs;
- recording protection/locks.

### Storage lifecycle

- explicit local StorageTarget;
- host-managed filesystems/RAID/ZFS/Btrfs/LVM/mergerfs/NAS rather than a zero-nvr storage-pool manager;
- configurable disk-pressure watermarks;
- retention policies;
- protected-recording safety;
- RecordingLocation for multiple verified copies;
- rclone copy/verify/delete/restore from the worker;
- OpenList optional for special cloud-drive adaptation;
- archive failure never stops healthy local recording;
- archive-before-local-delete when configured;
- no default `rclone move` or whole-tree sync semantics.

### Events, alerts, and notifications

- unified Event model;
- system events for camera/storage/component health;
- AlertPolicy limited to NVR-relevant conditions;
- Alert/acknowledgement lifecycle;
- notification history;
- SMTP/email;
- password-reset delivery;
- Apprise-backed delivery channels;
- outbound webhook/MQTT where configured.

Do not build a generic visual automation/expression engine.

### AI

Frigate is the primary supported optional AI provider for V1 integration.

Required integration semantics:

- Managed and/or External mode as deployment supports;
- Frigate owns detection/tracking/zones;
- zero-nvr normalizes events into its Event model;
- Frigate does not become recording authority;
- Frigate failure does not stop recording.

Advanced face recognition, LPR, multiple-provider fusion, and additional AI engines do not block V1.

### Authentication and authorization

- local users;
- secure password hashing;
- administrator/user management;
- password change;
- password reset;
- host-local emergency administrator recovery;
- roles and permissions;
- camera scope;
- session management;
- Personal API Tokens;
- audit;
- optional OIDC external identity.

Direct LDAP/SAML/IdP implementation is not required; external identity platforms may expose OIDC.

### Time correctness

- canonical UTC persistence;
- ISO 8601 API timestamps with timezone;
- configurable UI/system timezone;
- host time-sync health;
- camera clock-offset measurement where available;
- ONVIF/device time/NTP configuration where supported;
- no custom NTP server.

### Backup and recovery

V1 default:

```text
SQLite -> Online Backup API -> restic
PostgreSQL -> pg_dump -> restic
```

Required:

- scheduling;
- retention;
- periodic repository verification;
- RecoveryKit/master-secret recovery;
- clean-host restore;
- non-destructive media reconciliation;
- separation of system backup from recording archive;
- configuration export separate from disaster backup.

Litestream, pgBackRest, WAL/PITR, filesystem snapshots, and continuous replication are optional advanced capabilities and do not block V1.

### Upgrade and migration

- `deploy.sh update` as V1 upgrade authority;
- version/digest-pinned release identity;
- preflight;
- verified safety backup when required;
- Alembic schema migration;
- startup schema compatibility gate;
- health/reconciliation after upgrade;
- rollback path;
- SQLite <-> PostgreSQL migration as a separate controlled operation.

V1 does not require a browser-driven Docker orchestrator, unrestricted Docker socket, scheduled automatic self-update, or heavyweight UpgradePlan subsystem.

### System health

- capability-specific health;
- camera/media;
- recording;
- storage;
- archive;
- worker;
- database;
- optional AI/integrations;
- meaningful persisted state transitions;
- no high-frequency telemetry table in SQLite.

## Deployment/runtime boundary

Default non-AI Core target:

```text
2 images
3 containers

zero-nvr image:
  - API container
  - worker container

ZLMediaKit image:
  - media container
```

The zero-nvr/worker image may include small libraries/CLI tools:

- FFmpeg/ffprobe;
- rclone;
- restic;
- Apprise;
- ONVIF libraries;
- Authlib/auth libraries.

They do not deserve separate containers merely because they are separate capabilities.

Separate containers are justified for independent long-running services such as:

- ZLMediaKit;
- Frigate;
- OpenList managed mode;
- PostgreSQL managed mode;
- Mosquitto managed mode.

## V1 optional integrations

These may be supported/enabled without being mandatory runtime dependencies:

- Frigate;
- MQTT;
- Home Assistant REST/webhook/MQTT integration;
- OpenList;
- PostgreSQL;
- OIDC;
- SMTP relay;
- coturn when remote WebRTC requires it.

External Mode is preferred when the user already operates a compatible service.

## Non-blocking / post-V1 candidates

The following do not block V1 unless explicitly re-promoted:

- GB28181/WVP;
- advanced vendor-private SDK integrations;
- Home Assistant custom integration package;
- advanced face/LPR AI;
- multiple AI-provider fusion;
- mandatory Prometheus/Grafana;
- mandatory OpenTelemetry tracing;
- rclone FUSE/VFS streaming as the required playback path;
- Litestream/pgBackRest/PITR product integration;
- multi-node media topology;
- HA clustering/federation;
- Kubernetes;
- zero-nvr-managed RAID/JBOD/storage pooling.

## Explicit anti-scope

V1 must not reimplement mature infrastructure without a demonstrated product requirement.

Examples:

- custom RTSP stack;
- custom media server;
- custom MP4 recorder for normal recording;
- custom H.264/H.265 packet ring buffer;
- custom ONVIF SOAP/WSDL stack;
- custom cloud-drive protocol clients when rclone/OpenList already fit;
- custom notification providers when Apprise fits;
- custom backup repository engine when restic fits;
- custom generic job queue when Huey fits;
- custom IdP/LDAP/SAML platform;
- custom RAID/JBOD/filesystem manager;
- custom monitoring TSDB;
- in-app Docker orchestration.

## UI completeness rule

Every normal V1 administrative/user workflow must have usable UI.

CLI-only is acceptable for host/break-glass operations such as:

- deployment;
- emergency admin reset;
- disaster recovery/bootstrap;
- certain upgrade/rollback operations.

The UI should guide users to the relevant `deploy.sh` feature command when a managed deployment component is not installed.

## Release gates

V1 cannot be declared production-ready until:

- design-freeze media/storage POCs pass;
- 8-camera baseline validation passes;
- 16-camera extended benchmark is documented;
- Core static footprint target (<2 GB) is measured;
- Core idle-RAM target (<1 GB excluding page cache/large ZLM buffers) is measured;
- camera onboarding/live/recording/timeline/playback/event paths pass soak/recovery tests;
- SMTP/password recovery works;
- backup and clean-host restore including secrets works;
- storage/archive failure does not stop healthy local recording;
- protected footage is not silently deleted under disk pressure;
- lost recording hooks/control-plane restarts reconcile correctly;
- optional integrations can be absent without breaking Core;
- deploy.sh update/rollback safety path is tested.

## Scope-change rule

After V1 architecture freeze, a change that alters component ownership, recording authority, Core container boundaries, storage lifecycle, database-default policy, or deployment authority requires an ADR.

Adding an optional adapter that respects those boundaries does not require rewriting the core architecture.
