# Spec 0013 — First Production Release Scope and Completeness Policy

Status: **accepted**

## Goal

Define the release philosophy for zero-nvr's first production-ready release.

Core rule:

> The first production release is a complete long-term usable NVR product, not an MVP or feature-preview release.

Implementation may still proceed in phases for engineering order, but those phases do not represent separate product releases and do not defer known product-grade capabilities to an unspecified later version.

## Current V1 scope guard

The first production release remains complete rather than MVP-scoped, but completeness is defined by an end-to-end usable NVR lifecycle rather than implementing every possible surveillance integration.

The following do **not** block V1 unless explicitly re-promoted by product decision:

- GB28181/WVP;
- advanced vendor-private integrations beyond standard onboarding/PTZ/events needed by the target devices;
- advanced face/LPR AI features;
- mandatory Prometheus/Grafana deployment;
- rclone FUSE/VFS streaming as the required remote-playback path;
- multi-node media topology, clustering, or HA;
- Kubernetes.

V1 must still ship a complete lifecycle for the supported core: installation/initialization, camera onboarding, live view, continuous/scheduled/event recording, timeline/gaps, events, storage/retention/archive, remote restore playback, users/RBAC, password recovery/SMTP, time/NTP health, audit, export/protection, backup/restore, health, and upgrade.

See [Project Baseline](../PROJECT_BASELINE.md).

## Release terminology

The repository is a V2 rewrite of the earlier camera-recorder project.

For release planning, however:

```text
Phase 0..N
    = implementation sequence

First Production Release
    = all accepted first-release capabilities completed and integrated
```

Do not interpret Phase 8/9/10/11 as post-release work merely because they appear later in the roadmap.

## Complete-first principle

When a capability is already known to be necessary for a serious self-hosted NVR, design and include it in the first production release unless it is explicitly declared outside product scope.

Examples that are first-release scope:

- local authentication;
- SMTP/email delivery and password reset;
- role/permission/camera scope;
- session management and audit;
- SecretStore/key rotation/backup;
- complete device onboarding: ONVIF discovery, manual RTSP, multi-channel devices, capability/profile probing, stream-role selection, batch add, endpoint rediscovery;
- complete device runtime lifecycle: enable/disable/maintenance, revision-fenced reconnect, hot profile/credential/endpoint reconfiguration, capability drift, channel disappearance/return;
- ONVIF events/PTZ/time management;
- complete live monitor: multi-camera layouts, preview/main auto switching, WebRTC/fMP4/HLS fallback, H.265 compatibility, TURN, audio, snapshots, PTZ overlay, and two-way talk;
- continuous/schedule/event/manual/hybrid recording;
- prebuffer/event lifecycle;
- retention, locks, disk pressure, multi-disk failover;
- local/S3/rclone/OpenList storage;
- historical timeline and multi-camera playback;
- export/download;
- alerts/notifications;
- Home Assistant REST/MQTT/custom integration;
- optional AI provider integration such as Frigate;
- metrics/health/backup/restore/upgrade/rollback.

"Optional" means optional to enable/deploy, not optional to implement before the first production release.

## Known security/account completeness

The first production release includes:

- local username/password accounts;
- email address support;
- SMTP configuration and test delivery;
- self-service password reset by expiring one-time email link/token;
- administrator-issued one-time reset token;
- local host/CLI emergency administrator recovery;
- password-change session revocation;
- login rate limiting / brute-force protection;
- session/device management;
- TOTP MFA;
- MFA recovery codes;
- role/permission/camera scope;
- service principals/API tokens;
- audit history.

OIDC/SSO is also included as a supported first-release authentication option behind the same Principal/Role/Scope authorization model. Local accounts remain available for break-glass/local administration.

## SMTP is a core platform service

SMTP is not merely one alert plugin. It is a first-release platform capability used by:

```text
password reset
security/account notifications
alert delivery
system/storage health notifications
optional report/export notifications
```

Conceptual configuration:

```text
SmtpSettings
  enabled
  host
  port
  security_mode       starttls | tls | none
  username
  credential_secret_ref
  from_address
  from_name
  reply_to
  timeout_seconds
  enabled_for_password_reset
  enabled_for_alerts
```

SMTP password/credential material is stored through SecretStore.

Required operations:

```text
test connection
send test email
queue delivery
retry transient failures
record final delivery result
sanitize errors
```

Initial implementation must support authenticated STARTTLS and implicit TLS. Plain/no-TLS mode may be allowed only as an explicit administrator choice for trusted local relays.

## Password reset completeness

### Self-service email reset

User supplies username/email.

The public response is intentionally non-enumerating:

```text
If an eligible account exists, reset instructions have been sent.
```

If account is enabled and has a usable email address:

1. generate high-entropy one-time reset token;
2. store only token hash;
3. persist user_id, expires_at, used_at, requested metadata;
4. enqueue reset email;
5. user opens reset URL and sets a new password;
6. atomically mark token used;
7. revoke existing sessions according to policy, default all prior sessions;
8. audit request/completion without storing the token.

Default reset lifetime is configurable; a short lifetime such as 15 minutes is appropriate as an initial product default.

### Administrator reset

Administrator may create an expiring one-time reset token for a user.

Administrator does not learn the existing password and does not receive stored password material.

### Emergency local recovery

If no administrator can authenticate, host/Docker shell access provides a local recovery command.

Example conceptual command:

```text
zero-nvr admin create-password-reset <username>
```

The command returns a one-time reset token or performs an interactive local password reset without placing the password in process arguments.

There is no default unauthenticated remote "reset admin" backdoor.

## Notification completeness

First production release notification channels include at minimum:

- SMTP/email;
- Apprise-backed providers;
- webhook;
- Home Assistant actions;
- MQTT.

The complete alerting layer includes AlertIncident grouping, acknowledgement/resolution, severity, recurring quiet periods, temporary silences, escalation policies, notification storm protection, templates, snapshots/deep links, durable AlertDelivery retries, per-attempt diagnostics, target health, and Alert Center UI.

Failure of one notification channel never blocks event persistence or recording. See [Spec 0014](0014-alerting-notification-and-escalation.md).

## Integration completeness

First production release implements, while allowing deployment to disable:

- Home Assistant REST integration;
- MQTT integration and Home Assistant MQTT Discovery;
- Home Assistant custom integration package;
- Frigate DetectionProvider;
- TURN support for remote WebRTC.

A disabled integration has zero runtime requirement where practical.

## Operations completeness

The first production release includes operational features needed for long-term use:

- health/readiness;
- structured logs;
- metrics;
- audit UI;
- PostgreSQL full/differential/incremental backup and PITR;
- backup/restore with scheduled verification and isolated restore testing;
- SecretStore/keyring RecoveryKit recovery;
- encrypted portable backup including secrets;
- configuration-only export excluding secrets;
- signed/version-pinned upgrade flow with preflight, verified safety backup, schema migration compatibility gates, and rollback;
- guided SQLite ↔ PostgreSQL migration with validation/cutover/rollback;
- database migrations;
- storage reconciliation;
- recorder/runtime restart recovery;
- long-duration multi-camera soak tests.

## UI completeness

Every first-release backend capability that requires normal administration must have a usable UI unless explicitly designated CLI-only for break-glass/recovery.

Examples:

- camera/device management;
- live view;
- playback/timeline/events;
- recording policies;
- storage/pools/cloud archive;
- users/roles/scopes/sessions/MFA;
- SMTP/notifications;
- integrations;
- time/NTP;
- SecretStore/key health;
- backup/restore;
- audit;
- system health.

Emergency host recovery remains intentionally CLI-only.

## What may remain outside first release

Only capabilities that are genuinely outside the current single-product target may remain future work.

Examples may include:

- Kubernetes-first deployment;
- multi-site distributed cluster/federation;
- custom-built WebRTC server replacing ZLM;
- custom-built ONVIF SOAP stack;
- replacing mature vendor/protocol components without product benefit.

This is different from a known end-user feature being deferred merely to make the first release smaller.

## Roadmap rule

Every roadmap task belongs to the first production release unless explicitly marked:

```text
OUT OF CURRENT PRODUCT SCOPE
```

Terms such as "future", "later", "optional" must not be used to quietly postpone a known first-release feature.

"Optional" remains valid only for runtime/deployment activation.

## Release gate

The first production release is not declared complete until:

- all accepted specs required by the roadmap are implemented;
- core UI exists for all normal administrative/user workflows;
- failure/recovery paths are tested;
- security/account recovery works;
- SMTP/email reset works;
- database PITR, clean-host backup/restore including credentials, and RecoveryKit recovery are tested;
- storage/media recovery is tested;
- live/recording/playback/event paths pass long-duration validation;
- optional integrations can be disabled without harming core operation;
- enabled first-release integrations have acceptance tests.

## Invariants

1. Engineering phases are implementation ordering, not separate feature releases.
2. Known product-grade capabilities belong to the first production release by default.
3. Optional means optional to enable, not deferred implementation.
4. SMTP and email password reset are first-release platform capabilities.
5. Normal user/admin workflows have UI coverage; only explicit break-glass workflows may remain CLI-only.
6. Security, recovery, backup, monitoring, and upgrade are release features rather than post-release cleanup.
7. First release may still rely on mature external components; completeness does not mean reimplementing commodity protocols.
8. Scope reduction requires an explicit product decision, not silent roadmap deferral.


## Backup and disaster-recovery completeness

The first production release includes capability-aware backup targets, pgBackRest-backed PostgreSQL PITR, system snapshots, encrypted RecoveryKit, portable migration backup, retention, verification, scheduled restore testing, clean-host restore, and remote-media reconciliation.

System backup protects metadata/configuration/secrets recovery; remote recording archive protects media. The product must report local-only media separately from verified remote-protected media.

See [Spec 0015 — Backup, Disaster Recovery, PITR, and System Migration](0015-backup-disaster-recovery-and-pitr.md).

## Upgrade and migration completeness

The first production release includes stable/preview release channels, update checking, manual/scheduled upgrade policy, compatibility preflight, verified pre-upgrade safety points, Alembic migration classification, startup schema gates, automatic rollback where lossless, recovery-point rollback for incompatible changes, upgrade history/UI, and separate guided SQLite ↔ PostgreSQL migration.

See [Spec 0017 — Upgrade, Schema Migration, Database Migration, and Rollback](0017-upgrade-migration-and-rollback.md).


## Camera onboarding completeness

The first production release includes staged discovery candidates, stable device identity/deduplication, Device-versus-Camera channel modeling, manual RTSP, ONVIF discovery/probe, HIK/GB28181 identity correlation, multi-channel onboarding, SourceMediaProfile discovery, explainable auto stream-role selection, manual override, actual media verification, batch onboarding, and endpoint/profile refresh handling.

See [Spec 0018 — Camera Onboarding, Discovery, Capability Probe, and Stream Selection](0018-camera-onboarding-discovery-and-stream-selection.md).


## Device runtime completeness

The first production release includes reconstructable Device/Camera runtime supervision, config-revision/runtime-generation fencing, idempotent enable/disable/reconnect, targeted hot reconfiguration, planned and forced source-profile switching, event subscription lifecycle, capability drift handling, layered health, and multi-channel missing/return recovery.

See [Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift](0019-device-runtime-lifecycle-and-reconfiguration.md).


## Live-view completeness

The first production release includes short-lived authorized MediaSessions, multi-camera saved layouts, preview/main promotion, browser capability negotiation, WebRTC/fMP4/HLS fallback, H.265-compatible live resolution without changing recording quality, shared on-demand transcode, authenticated coturn TURN traversal, audio, snapshot, PTZ overlay, and separately authorized two-way talk.

See [Spec 0020 — Live View, Media Sessions, Adaptive Quality, TURN, and Talk](0020-live-view-media-session-and-talk.md).


## Detection and AI completeness

The first production release includes provider-neutral DetectionObservation/DetectionEvent handling, ONVIF/HIK native events, local lightweight motion, optional Frigate tracked-object integration, zones/object classes/sub-labels/snapshots, provider reconnect/liveness handling, conservative non-destructive event fusion, per-provider recording/alert eligibility, provider health, and Event Center filtering.

See [Spec 0021 — Detection Providers, AI Events, Object Tracking, Zones, and Event Fusion](0021-detection-providers-ai-events-and-fusion.md).
