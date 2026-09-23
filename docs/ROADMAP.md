# zero-nvr First Production Release Roadmap

This roadmap describes implementation sequencing, not separate product releases.

Core lifecycle tasks in this roadmap belong to the first production-ready zero-nvr release. Items explicitly marked OPTIONAL / POST-V1 do not block V1.

"Complete first release" means the supported NVR lifecycle has no dead end. It does not require every surveillance protocol, vendor SDK, observability stack, PITR engine, or multi-node feature to ship in V1.


## Design-freeze gate

Current project state: **V1 Architecture Frozen**.

The architecture-freeze gate is complete:

1. all 10 POCs in [plans/01-design-freeze-poc.md](plans/01-design-freeze-poc.md) have accepted runtime results;
2. the persistence boundary in [plans/02-v1-schema-freeze.md](plans/02-v1-schema-freeze.md) is frozen;
3. the public/internal API and module boundary in [plans/03-v1-api-module-freeze.md](plans/03-v1-api-module-freeze.md) is frozen;
4. [ADR 0011](adr/0011-v1-architecture-freeze.md) records the freeze and change-control rule.

POC gates:

1. ZLM continuous recording + hook indexing;
2. fMP4 abnormal termination recovery;
3. EVENT_ONLY ~10s pre-roll;
4. multi-event recording-window extension;
5. wall-clock/timeline precision;
6. ZLM VOD seek;
7. remote restore -> local cache -> ZLM playback;
8. ZLM stream sharing / camera connection count;
9. SQLite load at 8-camera baseline and 16-camera extended target;
10. recovery reconciliation after lost hooks/control-plane restart.

Resource targets are governed by [plans/04-v1-resource-budget.md](plans/04-v1-resource-budget.md):

- non-AI Core static footprint < 2 GB;
- non-AI Core idle RAM < 1 GB under the documented measurement method;
- 2–4 camera small-host soak around the 2 GB RAM / 2 CPU class;
- 8-camera baseline and 16-camera extended database/media benchmarks;
- bounded logs, cache, and EVENT_ONLY tmpfs.


## Phase 0 — Repository and architecture baseline

- [x] Initialize zero-nvr repository.
- [x] Define control-plane / device-plane / media-plane ownership.
- [x] Define reuse-first integration policy.
- [x] Define first canonical domain model.
- [x] Define event recording lifecycle, RecordingTrigger, correlation_id, and intent arbitration.
- [x] Define instant-event 10s pre-roll + 10s post-roll semantics.
- [x] Define required code-comment/documentation standard.
- [x] Freeze EVENT_ONLY pre/post-roll mechanism: one ZLM rolling short-fragment recorder in bounded tmpfs, whole-fragment promotion from RecordingTrigger windows.
- [x] Define canonical recording storage layout, UTC indexing, and cross-day behavior.
- [x] Define recording retention, disk-pressure cleanup, locks, and safe purge.
- [x] Define historical playback timeline, gaps, event markers, and multi-camera synchronization.
- [x] Define additive recording-requirement arbitration across continuous/schedule/event/manual/hybrid modes without a RecordingIntent table.
- [x] Define ZLM-owned media reconnect boundary, zero-nvr health projection, recovery reconciliation, and timeline-gap semantics.
- [x] Define canonical UTC, camera-clock offset handling, timezone semantics, and device time-sync policy.
- [x] Define explicit StorageTarget routing, host-managed disk aggregation/redundancy, disk pressure, and remote-archive separation.
- [x] Define authentication, role/permission model, camera scope, media authorization, and audit.
- [x] Define configuration/SecretStore separation, mature authenticated encryption, simple key rotation, and RecoveryKit semantics.
- [x] Define complete-first production release policy: core lifecycle ships complete; non-core integrations do not silently become release gates.
- [x] Define Event -> Alert -> NotificationDelivery lifecycle, cooldown, Apprise routing, and durable retry.
- [x] Define lightweight database/system backup with restic, RecoveryKit, verification, and clean-host disaster recovery.
- [x] Define SQLite-default + PostgreSQL-enhanced dual production database modes and migration strategy.
- [x] Define deploy.sh-driven upgrade preflight, safety backup, Alembic migration classes, rollback, and database cutover safety.
- [x] Define camera/device discovery, identity deduplication, multi-channel onboarding, capability probe, and stream-profile selection.
- [x] Define device runtime lifecycle, config revision fencing, hot reconfiguration, capability drift, and multi-channel runtime recovery.
- [x] Define live-view MediaSession, multi-grid quality switching, browser/codec fallback, bounded on-demand transcode, optional TURN/audio.
- [x] Define canonical Event normalization for ONVIF/Frigate/system sources and idempotent provider updates; generic event fusion deferred.
- [x] Complete reuse/ownership audit and remove duplicate media/storage/job/alert/secret implementations.
- [x] Freeze canonical V1 persistence boundary and explicit non-tables.
- [x] Complete API/module-boundary freeze document and public/internal ownership contract.
- [x] Commit executable harnesses and NOT RUN result records for all 10 design-freeze POCs.
- [x] Execute all design-freeze POCs on real Docker runners and record measured results/artifacts.
- [x] Declare V1 Architecture Frozen after POC + schema + API/module gates pass.

## Deployment-test gate

This gate is intentionally smaller than the complete V1 release gate. Once it
passes, zero-nvr should be deployed on a clean real host and exercised with a
real camera while the remaining V1 work continues.

- [x] `deploy.sh install` creates `.env` from `.env.example` when absent.
- [x] first install generates the Core application/ZLM bootstrap secrets.
- [x] remove the Core default host-port collision between zero-nvr API
  `8000/tcp` and ZLMediaKit WebRTC; WebRTC now defaults to
  `8001/tcp+udp`.
- [x] add install/feature host-port preflight before Compose mutation.
- [x] interactive TTY install: explain conflicts, suggest an available port,
  accept operator input, validate it, and persist the selected value to
  `.env`.
- [x] non-interactive/CI install: fail fast on conflicts with the exact env key
  and port; never block waiting for input.
- [x] validate the rendered Compose model before pull/build/start.
- [x] successful install prints the effective Web UI address and published
  media ports.
- [x] automated clean-install orchestration smoke: start from no `.env`,
  generate bootstrap secrets, create host paths, validate ports/Compose,
  render ZLM config, migrate/start/check, and print effective access ports
  using an isolated fake-Docker harness in Deployment CI.
- [x] complete the Camera Recording Settings UI so recording mode, schedule,
  segment duration, event pre/post-roll, storage target, and retention policy
  can be configured without direct API calls.
- [x] execute a clean-host Core install smoke test on a fresh Ubuntu runner
  with real Docker Compose: first-run .env/secrets, migration, API/worker/ZLM
  startup, health/schema checks, install summary, and clean teardown.
- [ ] execute one-real-camera live -> record -> finalized hook -> timeline ->
  playback -> restart/reconciliation smoke test on the intended deployment
  host. This is now the only remaining Deployment-test gate.

Roadmap synchronization note: Phase 1/2 contain historical unchecked items that
are already partially or fully implemented. They must be reconciled against the
repository before using checkbox counts as a completion metric; do not infer
that an unchecked historical bootstrap item is absent without inspecting the
current code/tests.

## Phase 1 — Platform foundation

- [x] Backend project bootstrap.
- [x] Frontend project bootstrap.
- [x] SQLAlchemy/Alembic shared logical schema for SQLite and PostgreSQL.
- [x] SQLite default production profile with WAL/busy-timeout/checkpoint/write-pressure health.
- [x] PostgreSQL optional bundled/external production profile.
- [x] SQLAlchemy repositories with small dialect-specific helpers only where SQLite/PostgreSQL genuinely differ.
- [x] SQLite and PostgreSQL production integration-test harnesses.
- [x] guided SQLite -> PostgreSQL migration with verified rollback-before-cutover safety.
- [x] guarded PostgreSQL -> SQLite migration with workload/schema preflight.
- [x] ordinary configuration + SecretStore abstraction.
- [x] SecretRecord persistence using mature authenticated encryption.
- [x] stable ZERO_NVR_SECRET_KEY / *_FILE bootstrap with simple versioned keyring rotation.
- [x] protected-file *_FILE bootstrap support for product master secret and external-service credentials.
- [x] secret redaction for logs/errors/traces/AuditEvent.
- [x] explicit keep/replace/clear credential update semantics.
- [x] credential validation before atomic secret_ref switch where practical.
- [x] User / Role / Permission / UserSession persistence.
- [x] first-run one-time administrator bootstrap with no default password.
- [x] local authentication with modern password hashing and session revocation.
- [x] User email field + verification state.
- [x] SMTP NotificationTarget(type=smtp) persistence/API with SecretStore-backed credentials and one system setting selecting the default security-email target.
- [x] SMTP connection test + test-email flow.
- [x] password-reset/security email delivery through NotificationDelivery + Huey retry/backoff/result tracking.
- [x] self-service email password reset with non-enumerating public response.
- [x] PasswordResetToken persistence using one-way token hashes.
- [x] administrator-issued one-time password reset token.
- [x] host/Docker CLI emergency administrator password recovery.
- [ ] OPTIONAL: TOTP MFA using a mature OTP library; must not block V1 release.
- [x] OIDC/SSO provider configuration and ExternalIdentity mapping.
- [x] login rate limiting / brute-force protection.
- [x] Personal API Token create/revoke/list flow with one-way token hashes.
- [x] built-in Administrator / Operator / Viewer roles.
- [x] CameraGroup + PrincipalCameraScope authorization.
- [x] centralized backend authorization dependencies/services.
- [x] short-lived scoped live/playback media session authorization.
- [x] integration authentication through scoped Personal API Tokens / provider credentials without introducing a generic service-principal framework in V1.
- [x] append-oriented AuditEvent persistence with secret redaction.
- [x] Structured logging and health/readiness.
- [x] Device / DeviceEndpoint / DeviceCredential / Camera / CameraStreamProfile / CameraStreamBinding schema from the V1 Schema Freeze.
- [x] namespaced system_settings persistence/API for recording timezone and managed-camera NTP policy; no dedicated SystemTimeSettings table.
- [x] Time Settings UI with DHCP/manual NTP source and ordered NTP server list.
- [x] canonical UTC/timezone configuration and host clock-health checks.
- [x] Adapter contracts.
- [x] Docker Compose development stack.

Acceptance:

- API + Web + default SQLite boot reliably.
- optional PostgreSQL profile boots reliably and passes the same core domain acceptance.
- empty Device Center works.
- migrations are repeatable.
- no media-specific code leaks into Camera domain.

## Phase 2 — ZLMediaKit Media Plane

- [x] Add ZLMediaKit service.
- [x] Implement MediaPlane contract.
- [x] Device / DeviceEndpoint / DeviceCredential persistence.
- [x] DiscoverySession / DiscoveryCandidate staging model backed by WS-Discovery/ONVIF discovery.
- [x] Manual ONVIF and Manual RTSP first-class onboarding; no default-password guessing or homemade LAN port scanner.
- [x] ONVIF profile/capability discovery first, ZLM actual-stream verification second, ffprobe only as fallback/recovery inspection.
- [x] CameraStreamProfile persistence and stream diagnostics.
- [x] canonical stream-purpose roles: RECORD / LIVE_HIGH / LIVE_LOW / AI_DETECT / SNAPSHOT / AUDIO where supported.
- [x] deterministic default profile binding with user override.
- [x] current Camera clock-offset/quality projection for ONVIF-capable devices; no high-frequency CameraClockStatus history table.
- [x] monitor/manage_ntp/ignore device-time mode where supported.
- [x] apply/verify camera NTP configuration without modifying host OS NTP service.
- [x] device clock offset/RTT/quality health diagnostics.
- [x] thin RuntimeReconciler that maps desired Camera configuration to ZLM/ONVIF adapter operations after restart.
- [x] config_revision/runtime_generation fencing only where needed to ignore stale adapter callbacks.
- [x] idempotent enable / disable / maintenance / configuration apply.
- [x] endpoint/credential/profile revalidation with the minimum required ZLM proxy change.
- [x] CameraStreamProfile refresh/diff and capability-drift detection.
- [x] planned recording-profile switch at a safe segment boundary where practical.
- [x] ONVIF event-subscription lifecycle using mature client-library facilities.
- [x] multi-channel missing/return lifecycle without Camera identity loss.
- [x] capability-specific health projection: control / media / recording / events / PTZ / clock.
- [x] ensure/remove ZLM stream proxy through a thin MediaPlane adapter.
- [x] consume ZLM registration/unregistration/recorder signals for observed media health.
- [x] configure ZLM-native pull/reconnect behavior; do not implement a competing RTSP reconnect/backoff engine.
- [x] recovery reconciliation after ZLM/API/control-plane restart.
- [x] MediaSession API with short-lived scoped authorization/revocation.
- [x] Browser capability report and LivePlaybackResolver.
- [x] WebRTC preferred transport with bounded fMP4/HLS fallback.
- [x] camera/live authorization before media-session issuance.
- [x] grid live_preview policy and focus/fullscreen live_main promotion/demotion.
- [x] viewport/network-aware auto quality with hysteresis.
- [x] live-session telemetry: bitrate/loss/RTT/jitter/first-frame/reconnect/relay.
- [x] H.265/H.264 browser compatibility resolution independent from recording profile.
- [x] TranscodeManager for on-demand H.265/incompatible-H.264 -> browser-compatible H.264.
- [x] shared transcode derivatives with refcount/idle TTL.
- [x] hardware-acceleration capability probe and CPU fallback/resource limits.
- [x] coturn STUN/TURN deployment and health.
- [x] short-lived authenticated TURN credentials.
- [x] direct/relayed ICE visibility and TURN bandwidth/session metrics.
- [x] live audio negotiation and focused-camera audio behavior.
- [x] live snapshot action without exposing camera snapshot URL.
- [x] PTZ overlay integrated with live view when authorized.
- [x] saved LiveViewLayout / grid layouts.
- [x] visibility/offscreen idle-session cleanup.
- [x] ZLM restart/session reconnect and current runtime-generation re-resolution.
- [x] Live Monitor complete UI.

Acceptance:

- one Camera can be added and viewed live without FastAPI decoding frames.
- multi-camera grid uses preview streams and promotes focused tiles to main quality.
- WebRTC failure can fall back to fMP4/HLS without exposing source credentials.
- H.265 recording can remain native while incompatible browsers receive a compatible live path.
- TURN, when enabled, uses short-lived credentials and does not become a Core dependency.
- media-engine restart is recoverable without losing Camera metadata.

## Phase 3 — Recording Plane

- [x] Implement per-camera recording arbiter that derives desired recorder state from RecordingPolicy + active RecordingTriggers.
- [x] Keep runtime arbitration idempotent without a mandatory RecordingIntent table.
- [x] Implement thin ZLM RecordingAdapter for start/stop/status and recorder hooks.
- [x] Keep FFmpeg out of the normal 24x7 recording path; use it only for derived/recovery jobs.
- [x] RecordingPolicy / Recording Settings persistence and API.
- [x] explicit schedule_timezone handling for wall-clock schedules.
- [x] Recording Settings UI for recording mode, nominal segment duration, and pre/post-roll; exact EVENT_ONLY pre-roll implementation follows the accepted POC result.
- [x] segment persistence.
- [x] UTC canonical recording timestamps and database timeline indexes.
- [x] map ZLM-native finalized recording paths into RecordingLocation without making filenames authoritative identity.
- [x] keep all canonical DB timestamps UTC; UI/path display timezone is presentation/configuration, not recording truth.
- [x] respect ZLM's own temporary-file/finalize semantics; zero-nvr must not add a second local media writer.
- [x] StorageTarget persistence and system default LOCAL_RECORDING target.
- [x] optional per-camera/policy explicit storage_target_id routing.
- [x] per-target filesystem health/free-space and configurable warning/high/critical watermarks.
- [x] host-managed ZFS/Btrfs/LVM/mergerfs/RAID/NAS guidance instead of zero-nvr disk pooling.
- [ ] local target failure health/alert behavior; no implicit cloud hot-recording fallback.
  - [x] System Health reports per-target availability and warning/high/critical capacity state.
  - [x] local recording failure/capacity pressure never implicitly falls back to cloud hot recording.
  - [ ] health transitions can create/resolve Alerts through the unified Phase 6 alert pipeline.
- [x] safe administrator target change/migration without losing historical RecordingLocations.
- [x] cross-day segments without midnight force-split.
- [x] source-loss finalized media tail is identified with `completion_reason = source_lost` without stretching media timing to the later unregister callback.
- [x] post-reconnect segments start in a new continuity generation and are never normalized against a pre-disconnect segment.
- [x] preserve RecordingPolicy/active RecordingTriggers across source outage and reconcile recorder plus prebuffer promotion state after ZLM recovery.
- [x] SystemEvent/health transition persistence sufficient to explain source-loss gaps when evidence exists.
- [x] recorder recovery / orphan and partial-file reconciliation.
- [x] RetentionPolicy + RecordingProtection persistence; retention horizon derived from policy/reasons/events.
- [x] normal age-based retention worker.
- [x] configurable disk-pressure watermarks (initial guidance 80/85/95%) and retention response.
- [x] priority-based emergency purge with structured logs.
- [x] RecordingProtection range create/update/delete and UI.
- [x] safe local purge only after verified remote readiness where applicable.
- [x] disk capacity guard.
- [x] basic timeline.

Acceptance:

- stable continuous recording.
- ZLM reconnect does not require Camera recreation.
- timeline accurately reflects stored segments.

## Phase 4 — ONVIF Device Plane

- [x] Integrate mature ONVIF library.
- [x] ONVIF WS-Discovery on selected local interfaces.
- [x] stable device-identity correlation/deduplication independent from IP address.
- [x] Device information + firmware/serial/stable identifier probe.
- [x] multi-channel/video-source enumeration for NVR/DVR/multi-sensor devices.
- [x] ONVIF Media Profiles -> CameraStreamProfile normalization.
- [x] stream URI retrieval without credential leakage.
- [x] per-role stream selection and actual pull verification.
- [ ] DeviceCapabilitySnapshot persistence/refresh.
- [ ] ONVIF Events capability + subscription path.
- [ ] PTZ capability/control after Events.
- [ ] snapshot/audio/time/NTP capability probing.
- [ ] DHCP endpoint-change rediscovery without recreating Camera IDs.
- [ ] identity-conflict UI instead of weak automatic merge.
- [ ] batch onboarding with shared/default credentials, groups, recording policy, StorageTarget and time-sync defaults.

Acceptance:

- no hand-written general SOAP/WSDL stack.
- discovery candidates do not create cameras before validation.
- one multi-channel recorder maps to one Device plus multiple Camera channels.
- stable device identity survives DHCP/IP changes.
- source profiles map into canonical recording/live/preview/detection roles.
- bad credentials or unpullable media fail onboarding without leaving silent half-configured cameras.

## Phase 5 — Events and Optional AI

- [ ] canonical Event persistence/API with source, source_event_id, camera, category, label, time range, confidence, zone, severity, snapshot_ref, metadata.
- [ ] idempotent UPSERT for provider new/update/end messages.
- [ ] native ONVIF event adapter using mature library subscription mechanisms.
- [ ] optional vendor-native event adapter only where ONVIF is insufficient.
- [ ] Frigate AIProviderInstance + Camera binding.
- [ ] Managed Frigate stream path through ZLM internal AI_DETECT stream.
- [ ] External Frigate connection/mapping mode.
- [ ] Frigate event/snapshot normalization without copying its full internal event schema.
- [ ] provider liveness/health transitions without high-frequency DB heartbeat rows.
- [ ] Event Center filters: camera / source / category / label / zone / confidence / date.
- [ ] Event detail drawer with snapshot, metadata, playback jump, protect/export actions.
- [ ] event snapshot priority: provider snapshot -> ZLM current snapshot -> FFmpeg historical fallback.

Acceptance:

- replayed provider messages do not create duplicate Events;
- Frigate new/update/end updates one Event;
- ONVIF events use the same Event API;
- Frigate/AI failure never interrupts healthy live/recording;
- Managed Frigate consumes the ZLM internal AI_DETECT stream and does not add a direct source-camera RTSP pull;
- source-facing camera reader/session count is unchanged when Managed Frigate is enabled;
- users with AI disabled do not need to pull or run Frigate;
- no generic EventFusion/DetectionObservation storage is required for V1.

## Phase 6 — Alerting and Notifications

- [ ] AlertPolicy persistence/API with NVR-specific predicates: camera/source/category/label/zone/confidence/duration/severity/schedule/cooldown.
- [ ] Alert persistence with active / acknowledged / resolved states.
- [ ] source-recovery handling for health Alerts.
- [ ] NotificationTarget persistence with SecretStore-backed credentials/config.
- [ ] NotificationDelivery persistence: pending / sending / sent / failed / suppressed.
- [ ] Huey-backed delivery retry with transient/permanent/rate-limited classification.
- [ ] Apprise integration as the default multi-channel delivery mechanism.
- [ ] SMTP configuration/test and password-reset delivery.
- [ ] outbound webhook and MQTT targets where configured.
- [ ] optional snapshot/deep-link attachment without permanent public media URLs.
- [ ] cooldown and notification-storm protection without dropping Events.
- [ ] optional RecordingProtection action for selected AlertPolicy.
- [ ] Alert Center UI: active/recent/filter/acknowledge/playback/delivery state.
- [ ] alert.view / alert.acknowledge / alert.manage / notification.view / notification.manage authorization.
- [ ] audit for policy/target/human acknowledgement and configuration changes.

Acceptance:

- repeated matching Events can suppress repeated sends during cooldown while every Event remains stored;
- acknowledgement never stops recording or changes Event truth;
- health recovery can resolve an Alert;
- SMTP/provider outage never stops recording;
- delivery retry survives worker restart;
- scoped users cannot access hidden-camera Alerts;
- no notification exposes camera/SecretStore credentials.

## Phase 7 — Storage and Cloud

- [ ] StorageTarget kinds/roles: LOCAL recording target and RCLONE archive target.
- [ ] StorageTarget / RecordingLocation persistence.
- [ ] local retention using RetentionPolicy + RecordingProtection.
- [ ] rclone-backed archive target configuration for S3/WebDAV/SFTP/SMB/OneDrive/etc.
- [ ] OpenList integration through rclone WebDAV rather than a separate file-transfer implementation.
- [ ] remote RecordingLocation lifecycle: ARCHIVING -> AVAILABLE / FAILED.
- [ ] remote verification before archive-required local deletion.
- [ ] safe local RecordingLocation deletion: AVAILABLE -> DELETING -> DELETED.
- [ ] archive upload policy independent from hot recording placement.
- [ ] block destructive StorageTarget removal when unique retained media exists.
- [ ] PlaybackResolver chooses RecordingLocation; remote-only playback restores to bounded local cache.

## Phase 8 — Historical Playback

- [ ] timezone-aware ISO 8601 PlaybackTimeline query API; frontend converts to milliseconds internally.
- [ ] range/detail-level timeline responses for day/hour/minute zoom.
- [ ] explicit segment availability: local / remote / cached_remote / missing / corrupted / purged.
- [ ] explicit gap reasons: not_scheduled / no_event / source_lost / runtime_restart / storage_failure / missing_media / purged / unknown.
- [ ] Canvas timeline with pan/zoom/shared playhead.
- [ ] event Marker ranges/points and zoom-aware aggregation.
- [ ] PlaybackResolver by RecordingSegment ID.
- [ ] playback/timeline camera-scope authorization and short-lived media access.
- [ ] local playback.
- [ ] ordered detailed segment ranges + binary absolute-time segment lookup.
- [ ] dual-player preload/ping-pong cross-segment continuation.
- [ ] standby-player readiness gating and absolute-boundary source switching.
- [ ] sub-pixel visual seam smoothing without mutating real gap data.
- [ ] monotonic Master Clock.
- [ ] drift correction with bounded rate convergence, hysteresis/cooldown, and hard-seek recovery.
- [ ] tolerant multi-camera synchronization as default.
- [ ] optional strict forensic synchronization.
- [ ] multi-camera aligned timeline query/track response.
- [ ] optional skip-gaps playback.
- [ ] playback speeds 0.5x / 1x / 2x / 4x / 8x.
- [ ] remote object resolver.
- [ ] playback cache.
- [ ] cloud-only playback.
- [ ] playback diagnostics.
- [ ] export.

Acceptance:

- seeking is based on absolute time rather than filenames.
- normal 5-minute boundaries do not look like separate recordings.
- known gaps visibly explain why media is unavailable.
- events remain readable from day overview to close zoom.
- one slow channel does not freeze all channels in default tolerant mode.
- strict mode can pause/re-align playable channels for synchronized review without treating legitimate gap channels as blockers.
- tiny real gaps may be visually smoothed at wide zoom but become visible again when zoomed in.
- cross-segment seek/switch behavior is validated across many consecutive 5-minute files.
- local and remote-only segments appear on one logical timeline.

## Phase 9 — Event Recording

- [ ] RecordingTrigger lifecycle for AI/ONVIF/HA/API/manual event recording requests.
- [x] derive desired recording state from baseline policy + active trigger windows.
- [ ] overlapping triggers extend one effective required-coverage/promotion interval without duplicate event recorders.
- [ ] continuous/scheduled/manual existing recording is annotated rather than restarted.
- [ ] Implement the POC-approved ZLM EVENT_ONLY rolling tmpfs + whole-fragment promotion mechanism.
- [ ] configurable pre_roll_seconds / post_roll_seconds.
- [ ] honest degraded-pre-roll state when required past coverage is unavailable.
- [ ] actual ZLM segment finalize hooks feed RecordingSegment catalog.
- [ ] Event -> RecordingSegment wall-clock linkage at query time.
- [ ] asynchronous explicit Export job for a single clip/file when requested.
- [ ] event-driven RecordingProtection action where policy requires it.
- [ ] no mandatory RecordingSession / RecordingIntent / PrebufferFragment / RecordingSessionSegment tables.

Acceptance:

- one camera has one normal ZLM recorder;
- two overlapping Events remain independent Events/Triggers and extend the same required media/promotion window;
- a new Event during post-roll extends the effective coverage deadline;
- continuous recording is never duplicated for Event clips;
- pre-roll behavior matches the accepted design-freeze POC.

## Phase 10 — Optional integrations and extensions

### V1 optional integrations

- [ ] Home Assistant REST/Webhook integration where useful.
- [ ] RecordingTrigger external automation flow.
- [ ] MQTT integration / Home Assistant MQTT Discovery.
- [ ] Frigate DetectionProvider with Managed and External modes.
- [ ] optional TURN support for remote WebRTC when deployment requires it.

Acceptance:

- integrations remain optional at deployment time;
- external sensor/AI triggers normalize into canonical Event/RecordingTrigger state;
- integration failure does not stop core recording, playback, storage, or authentication;
- Frigate never becomes the zero-nvr recording/system-of-record authority.

### POST-V1 / non-blocking candidates

- [ ] Home Assistant custom integration package.
- [ ] HIK/vendor-private bridge where ONVIF is insufficient.
- [ ] GB28181 / WVP.
- [ ] additional AI-provider adapters beyond the first production provider.
- [ ] advanced PTZ patrol/vendor-private features.

These items do not block V1 unless explicitly re-promoted by product decision.

## Phase 11 — Operations, Backup, Recovery, and Release

- [ ] SecretStore master/keyring rotation workflow and health UI using the accepted lightweight authenticated-encryption design.
- [ ] lightweight BackupPolicy / BackupSet persistence and APIs; BackupManifest remains a versioned artifact inside backup payloads.
- [ ] SQLite Online Backup API consistent snapshot backend.
- [ ] PostgreSQL pg_dump backup backend.
- [ ] restic backup repository integration, retention, snapshot identity, and periodic check.
- [ ] encrypted RecoveryKit generation/download/staleness tracking.
- [ ] backup-target bootstrap recovery without depending on the lost production database.
- [ ] scheduled/manual/pre-upgrade backup reasons and protected rollback retention.
- [ ] clean-host restore via deploy.sh + compatible release + RecoveryKit.
- [ ] restore diagnostics for missing/wrong keyring and unavailable repository credentials.
- [ ] non-destructive post-restore RecordingLocation/media reconciliation.
- [ ] configuration-only export distinct from disaster backup.
- [ ] backup/restore authorization and audit.
- [ ] Backup & Recovery UI for normal administration.
- [ ] user/role/camera-scope administration UI.
- [ ] audit UI.
- [ ] release manifest/version/digest compatibility metadata.
- [ ] update-availability/version display in System UI.
- [ ] deploy.sh update preflight: version/schema/DB/component/free-space/keyring/backup checks.
- [ ] mandatory verified pre-upgrade safety backup for incompatible/non-reconstructable changes.
- [ ] Alembic migration classes A/B/C and SQLite batch/table-rebuild safety.
- [ ] PostgreSQL bounded-lock/restartable migration behavior where required.
- [ ] startup application/database/schema compatibility gate.
- [ ] pinned previous artifacts until successful update/rollback decision.
- [ ] post-upgrade readiness and media/catalog reconciliation.
- [ ] rollback command/path for compatible and recovery-point rollback.
- [ ] separate SQLite <-> PostgreSQL migration workflow with validation and rollback grace period.
- [ ] deploy.sh status / doctor / backup / restore / rollback flows.
- [ ] long-duration 8-camera baseline acceptance.
- [ ] 16-camera extended-target benchmark.
- [ ] execute Plan 04 R1 clean-Core image/static-footprint + no-camera idle measurement.
- [ ] execute Plan 04 R2/R3 2-camera and 4-camera small-host soaks.
- [ ] Core static footprint < 2 GB validation.
- [ ] Core idle RAM < 1 GB validation under the documented resource-budget measurement method.
- [ ] verify Docker log rotation, cache byte quota, and EVENT_ONLY tmpfs bounds.

Optional/non-blocking operational extensions:

- [ ] Prometheus/OpenTelemetry export.
- [ ] Grafana example dashboards.
- [ ] Litestream/pgBackRest/PITR integration if later justified.
- [ ] multi-host media/storage topology evaluation.

## Out of current product scope

These are intentionally outside the first production release because mature components already satisfy the need or the capability belongs to a different deployment class:

- hand-written general ONVIF SOAP/WSDL stack;
- a custom WebRTC server replacing ZLMediaKit;
- custom generic cloud-drive implementations replacing S3/rclone/OpenList adapters;
- making Frigate a competing NVR/source-of-truth database;
- Kubernetes-first deployment;
- distributed multi-site/multi-host clustering/federation;
- a zero-nvr-managed RAID/JBOD/StoragePool layer;
- a competing RTSP packet monitor/reconnect engine beside ZLMediaKit;
- mandatory PITR/replication infrastructure for V1;
- an in-app Docker orchestrator or unrestricted Docker-socket control.

See [Spec 0013 — First Production Release Scope and Completeness Policy](specs/0013-first-production-release-scope.md).
