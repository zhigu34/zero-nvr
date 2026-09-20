# zero-nvr First Production Release Roadmap

This roadmap describes implementation sequencing, not separate product releases.

Core lifecycle tasks in this roadmap belong to the first production-ready zero-nvr release. Items explicitly marked OPTIONAL / POST-V1 do not block V1.

"Complete first release" means the supported NVR lifecycle has no dead end. It does not require every surveillance protocol, vendor SDK, observability stack, PITR engine, or multi-node feature to ship in V1.


## Design-freeze gate

Current project state: **V1 Design Freeze Candidate**.

Before core architecture is declared frozen, complete the POCs in [plans/01-design-freeze-poc.md](plans/01-design-freeze-poc.md):

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

Resource targets to benchmark:

- Core static footprint < 2 GB;
- Core idle RAM < 1 GB excluding page cache and large ZLM buffers;
- 8 cameras baseline;
- 16 cameras extended target.


## Phase 0 — Repository and architecture baseline

- [x] Initialize zero-nvr repository.
- [x] Define control-plane / device-plane / media-plane ownership.
- [x] Define reuse-first integration policy.
- [x] Define first canonical domain model.
- [x] Define event recording lifecycle, RecordingTrigger, correlation_id, and intent arbitration.
- [x] Define instant-event 10s pre-roll + 10s post-roll semantics.
- [x] Define required code-comment/documentation standard.
- [x] Define EVENT_ONLY pre/post-roll semantics; exact ZLM-native pre-roll mechanism remains a design-freeze POC.
- [x] Define canonical recording storage layout, UTC indexing, and cross-day behavior.
- [x] Define recording retention, disk-pressure cleanup, locks, and safe purge.
- [x] Define historical playback timeline, gaps, event markers, and multi-camera synchronization.
- [x] Define additive recording-intent arbitration across continuous/schedule/event/manual/hybrid modes.
- [x] Define ZLM-owned media reconnect boundary, zero-nvr health projection, recovery reconciliation, and timeline-gap semantics.
- [x] Define canonical UTC, camera-clock offset handling, timezone semantics, and device time-sync policy.
- [x] Define explicit StorageTarget routing, host-managed disk aggregation/redundancy, disk pressure, and remote-archive separation.
- [x] Define authentication, role/permission model, camera scope, media authorization, and audit.
- [x] Define configuration/SecretStore separation, envelope encryption, key rotation, and encrypted backup semantics.
- [x] Define complete-first production release policy: core lifecycle ships complete; non-core integrations do not silently become release gates.
- [x] Define alert incident lifecycle, grouping/cooldown, escalation, silences, notification routing, and durable delivery.
- [x] Define lightweight database/system backup with restic, RecoveryKit, verification, and clean-host disaster recovery.
- [x] Define SQLite-default + PostgreSQL-enhanced dual production database modes and migration strategy.
- [x] Define deploy.sh-driven upgrade preflight, safety backup, Alembic migration classes, rollback, and database cutover safety.
- [x] Define camera/device discovery, identity deduplication, multi-channel onboarding, capability probe, and stream-profile selection.
- [x] Define device runtime lifecycle, config revision fencing, hot reconfiguration, capability drift, and multi-channel runtime recovery.
- [x] Define complete live-view MediaSession, multi-grid quality switching, WebRTC/fMP4/HLS fallback, TURN, H.265 compatibility, audio, and talk.
- [x] Define DetectionProvider observations, AI/object tracking, zones, provider liveness, and non-destructive event fusion.
- [ ] Review and refine remaining architecture decisions before implementation.

## Phase 1 — Platform foundation

- [ ] Backend project bootstrap.
- [ ] Frontend project bootstrap.
- [ ] SQLAlchemy/Alembic shared logical schema for SQLite and PostgreSQL.
- [ ] SQLite default production profile with WAL/busy-timeout/checkpoint/write-pressure health.
- [ ] PostgreSQL optional bundled/external production profile.
- [ ] DatabaseCapabilities abstraction for locking/task claiming/indexing/backup.
- [ ] SQLite and PostgreSQL production integration-test harnesses.
- [ ] guided SQLite -> PostgreSQL migration with verified rollback-before-cutover safety.
- [ ] guarded PostgreSQL -> SQLite migration with workload/schema preflight.
- [ ] ordinary configuration + SecretStore abstraction.
- [ ] SecretRecord persistence with authenticated envelope encryption.
- [ ] per-record DEK + external/versioned KEK keyring bootstrap.
- [ ] Docker secret / protected-file *_FILE bootstrap support.
- [ ] secret redaction for logs/errors/traces/AuditEvent.
- [ ] explicit keep/replace/clear credential update semantics.
- [ ] credential validation before atomic secret_ref switch where practical.
- [ ] User / Role / Permission / UserSession persistence.
- [ ] first-run one-time administrator bootstrap with no default password.
- [ ] local authentication with modern password hashing and session revocation.
- [ ] User email field + verification state.
- [ ] SMTP settings persistence/API and SecretStore-backed credentials.
- [ ] SMTP connection test + test-email flow.
- [ ] queued SMTP delivery with retry/backoff/result tracking.
- [ ] self-service email password reset with non-enumerating public response.
- [ ] PasswordResetToken persistence using one-way token hashes.
- [ ] administrator-issued one-time password reset token.
- [ ] host/Docker CLI emergency administrator password recovery.
- [ ] TOTP MFA enrollment/challenge/disable flow.
- [ ] one-time MFA recovery codes stored as hashes.
- [ ] OIDC/SSO provider configuration and ExternalIdentity mapping.
- [ ] login rate limiting / brute-force protection.
- [ ] one-way hashing for verifier-only service/API tokens.
- [ ] built-in Administrator / Operator / Viewer roles.
- [ ] CameraGroup + PrincipalCameraScope authorization.
- [ ] centralized backend authorization dependencies/services.
- [ ] short-lived scoped live/playback media session authorization.
- [ ] service-principal credentials for integrations.
- [ ] append-oriented AuditEvent persistence with secret redaction.
- [ ] Structured logging and health/readiness.
- [ ] Base Camera / CameraConnection schema.
- [ ] SystemTimeSettings persistence/API for recording timezone and managed-camera NTP settings.
- [ ] Time Settings UI with DHCP/manual NTP source and ordered NTP server list.
- [ ] canonical UTC/timezone configuration and host clock-health checks.
- [ ] Adapter contracts.
- [ ] Docker Compose development stack.

Acceptance:

- API + Web + default SQLite boot reliably.
- optional PostgreSQL profile boots reliably and passes the same core domain acceptance.
- empty Device Center works.
- migrations are repeatable.
- no media-specific code leaks into Camera domain.

## Phase 2 — ZLMediaKit Media Plane

- [ ] Add ZLMediaKit service.
- [ ] Implement MediaPlane contract.
- [ ] Device / DeviceEndpoint / DeviceCredential persistence.
- [ ] DiscoverySession / DiscoveryCandidate staging model.
- [ ] bounded manual IP/hostname/CIDR probe framework.
- [ ] Manual RTSP first-class onboarding with URI credential extraction into SecretStore.
- [ ] actual media pull/ffprobe/ZLM verification before marking Camera verified.
- [ ] SourceMediaProfile persistence and stream diagnostics.
- [ ] canonical MediaStream roles: recording / live_main / live_preview / detection / audio.
- [ ] deterministic auto profile selection with reason/score diagnostics.
- [ ] manual per-role profile override and invalid-profile fallback warnings.
- [ ] CameraClockStatus sampling for ONVIF-capable devices.
- [ ] optional monitor/manage_ntp/ignore device-time mode.
- [ ] inherit system managed-camera NTP settings with optional per-camera NTP override.
- [ ] apply/verify managed-camera NTP configuration without modifying host OS NTP service.
- [ ] device clock offset/RTT/quality health diagnostics.
- [ ] RuntimeSupervisor for reconstructing desired Device/Camera runtimes after restart.
- [ ] monotonic config_revision + runtime_generation fencing for ZLM/probe/event callbacks.
- [ ] idempotent enable / disable / maintenance / reconnect operations.
- [ ] prepare -> validate -> commit -> apply runtime configuration pipeline.
- [ ] metadata-only change classification with zero media restart.
- [ ] endpoint/credential hot revalidation and targeted reconnect.
- [ ] SourceMediaProfile refresh/diff and capability-drift detection.
- [ ] planned recording-profile switch at safe formal segment boundary.
- [ ] forced source/profile switch with completion_reason = source_reconfigured while preserving RecordingSession/Intent.
- [ ] live_main/live_preview shadow-runtime handoff.
- [ ] detection runtime generation handoff and stale stateful-event closure.
- [ ] event-subscription lifecycle/renew/reconnect with generation fencing.
- [ ] multi-channel missing/return lifecycle without Camera identity loss.
- [ ] layered runtime health: control / media / recording / events / PTZ / clock / capability.
- [ ] Ensure/remove stream proxy.
- [ ] per-camera source runtime state machine: streaming / degraded / reconnecting / offline.
- [ ] ZLM source registration/unregistration + pull-proxy close/error integration.
- [ ] configurable reconnect backoff/jitter and offline threshold.
- [ ] infinite/background retry while camera remains enabled.
- [ ] Stream runtime health.
- [ ] MediaSession API with short-lived scoped authorization/revocation.
- [ ] Browser capability report and LivePlaybackResolver.
- [ ] WebRTC preferred transport with bounded fMP4/HLS fallback.
- [ ] camera/live authorization before media-session issuance.
- [ ] grid live_preview policy and focus/fullscreen live_main promotion/demotion.
- [ ] viewport/network-aware auto quality with hysteresis.
- [ ] live-session telemetry: bitrate/loss/RTT/jitter/first-frame/reconnect/relay.
- [ ] H.265/H.264 browser compatibility resolution independent from recording profile.
- [ ] TranscodeManager for on-demand H.265/incompatible-H.264 -> browser-compatible H.264.
- [ ] shared transcode derivatives with refcount/idle TTL.
- [ ] hardware-acceleration capability probe and CPU fallback/resource limits.
- [ ] coturn STUN/TURN deployment and health.
- [ ] short-lived authenticated TURN credentials.
- [ ] direct/relayed ICE visibility and TURN bandwidth/session metrics.
- [ ] live audio negotiation and focused-camera audio behavior.
- [ ] camera.talk permission and TalkSession API.
- [ ] TalkBackend abstraction for ONVIF/RTSP/HIK/GB28181 backchannels.
- [ ] push-to-talk + full-duplex where supported; single-talker lease default.
- [ ] live snapshot action without exposing camera snapshot URL.
- [ ] PTZ overlay integrated with live view when authorized.
- [ ] saved LiveViewLayout / grid layouts.
- [ ] visibility/offscreen idle-session cleanup.
- [ ] ZLM restart/session reconnect and current runtime-generation re-resolution.
- [ ] Live Monitor complete UI.

Acceptance:

- one Camera can be added and viewed live without FastAPI decoding frames.
- multi-camera grid uses preview streams and promotes focused tiles to main quality.
- WebRTC failure can fall back to fMP4/HLS without exposing source credentials.
- H.265 recording can remain native while incompatible browsers receive a compatible live path.
- TURN supports authenticated remote WebRTC and reports relay state.
- talk is separately authorized and does not affect video/recording on failure.
- media-engine restart is recoverable without losing Camera metadata.

## Phase 3 — Recording Plane

- [ ] Implement RecordingManager per-camera intent arbiter.
- [ ] RecordingIntent persistence/recovery and idempotent transitions.
- [ ] Implement thin ZLM RecordingAdapter for start/stop/status and recorder hooks.
- [ ] Keep FFmpeg out of the normal 24x7 recording path; use it only for derived/recovery jobs.
- [ ] RecordingPolicy / Recording Settings persistence and API.
- [ ] explicit schedule_timezone handling for wall-clock schedules.
- [ ] Recording Settings UI for recording mode, nominal segment duration, and pre/post-roll; exact EVENT_ONLY pre-roll implementation follows the accepted POC result.
- [ ] segment persistence.
- [ ] UTC canonical recording timestamps and database timeline indexes.
- [ ] compact human-readable local recording layout: name-id / date / name-id_date_start.mp4.
- [ ] configurable effective recording timezone for all generated path/date/time values while DB stays UTC.
- [ ] per-camera _camera.json convenience metadata for detached-disk browsing.
- [ ] staging/atomic finalize and backend object-key mapping.
- [ ] StorageTarget persistence and system default LOCAL_RECORDING target.
- [ ] optional per-camera/policy explicit storage_target_id routing.
- [ ] per-target filesystem health/free-space and configurable warning/high/critical watermarks.
- [ ] host-managed ZFS/Btrfs/LVM/mergerfs/RAID/NAS guidance instead of zero-nvr disk pooling.
- [ ] local target failure health/alert behavior; no implicit cloud hot-recording fallback.
- [ ] safe administrator target change/migration without losing historical RecordingLocations.
- [ ] cross-day segments without midnight force-split.
- [ ] source-loss segment finalize with completion_reason = source_lost.
- [ ] post-reconnect new segment clock anchored at actual recovery time.
- [ ] preserve RecordingSession/RecordingIntent across transport outage.
- [ ] SourceConnectivityIncident persistence and gap explanation.
- [ ] recorder recovery / orphan and partial-file reconciliation.
- [ ] RetentionPolicy / RetentionClaim persistence.
- [ ] normal age-based retention worker.
- [ ] configurable disk-pressure watermarks (initial guidance 80/85/95%) and retention response.
- [ ] priority-based emergency purge with structured logs.
- [ ] recording/event/range lock and unlock.
- [ ] safe local purge only after verified remote readiness where applicable.
- [ ] disk capacity guard.
- [ ] basic timeline.

Acceptance:

- stable continuous recording.
- ZLM reconnect does not require Camera recreation.
- timeline accurately reflects stored segments.

## Phase 4 — ONVIF Device Plane

- [ ] Integrate mature ONVIF library.
- [ ] ONVIF WS-Discovery on selected local interfaces.
- [ ] stable device-identity correlation/deduplication independent from IP address.
- [ ] Device information + firmware/serial/stable identifier probe.
- [ ] multi-channel/video-source enumeration for NVR/DVR/multi-sensor devices.
- [ ] ONVIF Media Profiles -> SourceMediaProfile normalization.
- [ ] stream URI retrieval without credential leakage.
- [ ] per-role stream selection and actual pull verification.
- [ ] DeviceCapabilitySnapshot persistence/refresh.
- [ ] ONVIF Events capability + subscription path.
- [ ] PTZ capability/control after Events.
- [ ] snapshot/audio/time/NTP capability probing.
- [ ] DHCP endpoint-change rediscovery without recreating Camera IDs.
- [ ] identity-conflict UI instead of weak automatic merge.
- [ ] batch onboarding with shared/default credentials, groups, recording policy, StoragePool and time-sync defaults.

Acceptance:

- no hand-written general SOAP/WSDL stack.
- discovery candidates do not create cameras before validation.
- one multi-channel recorder maps to one Device plus multiple Camera channels.
- stable device identity survives DHCP/IP changes.
- source profiles map into canonical recording/live/preview/detection roles.
- bad credentials or unpullable media fail onboarding without leaving silent half-configured cameras.

## Phase 5 — Event Detection Platform

- [ ] DetectionProvider contract and provider capability model.
- [ ] DetectionProviderInstance persistence/health.
- [ ] DetectionProviderBinding per Camera with independent timeline / recording / alert eligibility.
- [ ] DetectionObservation append-oriented provider evidence and durable ingress idempotency.
- [ ] DetectionEvent provider-neutral aggregate with START / UPDATE / END and instant lifecycle.
- [ ] source_occurred_at / received_at / occurred_at timestamp provenance and clock-offset correction.
- [ ] object_class / object_subclass / confidence / bounding-box normalization.
- [ ] bounded observation sampling/retention to protect SQLite/PostgreSQL write/storage load.
- [ ] EventZone normalized polygons + ProviderZoneBinding.
- [ ] DetectionEventZoneInterval entry/exit history.
- [ ] DetectionPolicy per Camera for provider/filter/snapshot/fusion behavior.
- [ ] provider disconnect liveness deadlines and provider_lost event completion.
- [ ] out-of-order provider update protection; completed events cannot be reopened by stale updates.
- [ ] native ONVIF event provider with PullPoint renew/reconnect/sync handling.
- [ ] HIK/vendor native event provider through isolated bridge.
- [ ] optional Frigate provider using MQTT tracked-object lifecycle + API health/detail/snapshot reconciliation.
- [ ] explicit Frigate Camera -> zero-nvr Camera mapping; Frigate remains non-authoritative.
- [ ] Frigate zones/object classes/sub-labels/snapshots normalization.
- [ ] Frigate review-context enrichment without duplicating each underlying tracked-object DetectionEvent.
- [ ] optional local lightweight motion using detection stream, resource limits, hysteresis + START/END holds.
- [ ] pulse-only source normalization/hold timeout.
- [ ] snapshot evidence import into zero-nvr StorageObject with failure isolation.
- [ ] face/LPR/sub-label metadata handling with redaction/scope/export controls.
- [ ] EventFusionGroup / EventFusionMember conservative cross-provider correlation.
- [ ] timeline fusion presentation with provider detail drill-down.
- [ ] structured EventLog persistence/query.
- [ ] Event Center filters for provider / event type / object class / zone / confidence / fusion.
- [ ] provider health metrics: lag/backlog/reconnect/invalid/deduplicated/active events.
- [ ] provider settings + per-camera bindings / zone mapping / eligibility UI.

Acceptance:

- replayed/duplicate provider messages do not create duplicate DetectionEvents.
- Frigate new/update/end for one tracked object maps to one stateful DetectionEvent.
- ONVIF/HIK state changes normalize into canonical lifecycle semantics.
- provider outage cannot leave event recording active forever.
- out-of-order stale updates cannot reopen completed events.
- multiple provider reports may correlate into one fusion group while every source event remains queryable.
- provider snapshot/AI failure never interrupts healthy media recording.
- Frigate/AI remains an optional event provider rather than NVR source of truth.
## Phase 6 — Alerting and Notifications

- [ ] AlertSignal normalization for detection / health / security sources.
- [ ] AlertRule persistence/API with camera scope, event/health/security filters, schedules, severity, grouping, cooldown, and resolution mode.
- [ ] AlertIncident + AlertIncidentSource lifecycle.
- [ ] active/resolved and acknowledged/unacknowledged state model.
- [ ] source / auto-timeout / manual incident resolution.
- [ ] grouping window and notification cooldown semantics without dropping DetectionEvents.
- [ ] EscalationPolicy / EscalationStep persistence and restart-safe timers.
- [ ] AlertActionSet / AlertAction reusable routing.
- [ ] NotificationTarget persistence and independent health.
- [ ] RecipientGroup and verified-user email recipients.
- [ ] NotificationTemplate built-ins + sandboxed customization/preview.
- [ ] AlertSilence temporary maintenance windows.
- [ ] recurring quiet schedules using explicit timezone/DST semantics.
- [ ] notification storm/rate protection without dropping incidents/events.
- [ ] durable AlertDelivery + AlertDeliveryAttempt state.
- [ ] idempotency-keyed worker processing.
- [ ] retry classification: transient / permanent / rate-limited / configuration.
- [ ] persisted retry/backoff/jitter and manual failed-delivery retry.
- [ ] SMTP/email NotificationBackend.
- [ ] email templates for detection, security, password reset, camera/system/storage health and recovery.
- [ ] Apprise target.
- [ ] signed/authenticated webhook target.
- [ ] Home Assistant notification/action target.
- [ ] MQTT notification target.
- [ ] optional event snapshot attachment and authenticated deep links.
- [ ] rule preview, target test, and template preview.
- [ ] Alert Center UI with filters, source events, acknowledgement, resolution, delivery history and retry.
- [ ] alert.view / alert.acknowledge / alert.manage / notification.view / notification.manage authorization.
- [ ] audit for rule/silence/target/template/human incident actions.

Acceptance:

- repeated motion bursts do not flood notifications while all DetectionEvents remain stored.
- active/recovered health conditions open/resolve incidents correctly.
- acknowledgement can stop escalation without pretending the source recovered.
- SMTP/provider outage never stops recording and other channels continue independently.
- retry/escalation/silence state survives worker/API restart.
- scoped users cannot see or acknowledge hidden-camera incidents.
- no notification exposes camera credentials, SecretStore values, or permanent public playback URLs.

## Phase 7 — Storage and Cloud

- [ ] StorageTarget roles: recording_hot / archive_remote / playback_cache / backup.
- [ ] StorageTarget / StorageObject.
- [ ] local retention.
- [ ] S3 adapter with SecretStore-backed credentials.
- [ ] upload state machine.
- [ ] remote verification.
- [ ] rclone adapter with SecretStore-backed credentials.
- [ ] OpenList adapter with SecretStore-backed credentials.
- [ ] safe local purge.
- [ ] archive upload policy independent from hot recording placement.
- [ ] block destructive StorageTarget removal when unique retained media exists.
- [ ] playback across multiple local targets + remote archive through PlaybackResolver.

## Phase 8 — Historical Playback

- [ ] UTC-millisecond PlaybackTimeline query API.
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

- [ ] RecordingSession lifecycle as one uninterrupted formal-recording interval.
- [ ] additive continuous/schedule/event/manual RecordingIntent arbitration.
- [ ] hybrid policy: scheduled baseline + outside-schedule event recording.
- [ ] manual start/stop affects only manual intent.
- [ ] intent changes must not reset formal segment cadence.
- [ ] segment promotion.
- [ ] ZLM rolling MP4 idle pre-buffer with configurable 20s default physical segments.
- [ ] formal recording with configurable 5min default physical segments.
- [ ] session-anchored formal segment clock: all healthy intermediate segments follow configured duration.
- [ ] segment completion_reason for normal boundary/session end vs abnormal partial segments.
- [ ] bounded tmpfs pre-buffer storage only while no formal recording is active.
- [ ] single recording-pipeline state transition: idle tmpfs prebuffer → formal recording without recorder restart.
- [ ] model 20s idle MP4 files as temporary PrebufferFragments, not formal RecordingSegments.
- [ ] anchor the first formal 5min segment window at RecordingSession logical start, including pre-roll.
- [ ] assemble protected prebuffer prefix + persistent continuation into the first finalized formal RecordingSegment without mandatory video re-encode.
- [ ] switch subsequent active-session segments to configurable 5min formal segmentation/persistent storage.
- [ ] finalize the last formal segment early at RecordingSession completion when needed.
- [ ] resume pre-buffer immediately after recording completion and bridge warm-up from the previous recording tail.
- [ ] on_record_mp4 segment-finalize ingestion.
- [ ] event-time current/previous segment protection + timestamp-based coverage validation.
- [ ] 10s default pre-roll buffer.
- [ ] dynamic stateful event recording with no fixed motion recording duration.
- [ ] instant-event recording as zero-duration Marker with 10s pre-roll + 10s post-roll.
- [ ] 10s default post-roll after the final active event ends.
- [ ] cancel/recalculate pending post-roll stop when a new event arrives.
- [ ] multiple independent Event markers sharing one RecordingSession.
- [ ] RecordingSessionSegment logical range links across physical MP4 segments.
- [ ] event-to-segment/session links.
- [ ] cross-segment playback without mandatory merge.
- [ ] asynchronous single-file crop/concat export.
- [ ] continuous/manual/schedule recording annotation without recorder restart.
- [ ] hybrid recording policy.

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

- [ ] SecretStore KEK rotation workflow and health UI.
- [ ] lightweight BackupPolicy / BackupSet / BackupManifest persistence and APIs.
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
- [ ] Core static footprint < 2 GB validation.
- [ ] Core idle RAM < 1 GB target validation, excluding page cache/large ZLM buffers.

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
