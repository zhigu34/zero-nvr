# zero-nvr First Production Release Roadmap

This roadmap describes implementation sequencing, not separate product releases.

Every task in this roadmap belongs to the first production-ready zero-nvr release unless explicitly marked OUT OF CURRENT PRODUCT SCOPE.

"Optional" means optional to enable/deploy, not deferred implementation.

## Phase 0 — Repository and architecture baseline

- [x] Initialize zero-nvr repository.
- [x] Define control-plane / device-plane / media-plane ownership.
- [x] Define reuse-first integration policy.
- [x] Define first canonical domain model.
- [x] Define stateful event recording lifecycle and RTSP motion state machine.
- [x] Define instant-event 10s pre-roll + 10s post-roll semantics.
- [x] Define required code-comment/documentation standard.
- [x] Define ZLM rolling MP4/tmpfs event pre-buffer and cross-segment composition.
- [x] Define canonical recording storage layout, UTC indexing, and cross-day behavior.
- [x] Define recording retention, disk-pressure cleanup, locks, and safe purge.
- [x] Define historical playback timeline, gaps, event markers, and multi-camera synchronization.
- [x] Define additive recording-intent arbitration across continuous/schedule/event/manual/hybrid modes.
- [x] Define stream-loss detection, reconnect, physical-segment recovery, and timeline-gap semantics.
- [x] Define canonical UTC, camera-clock offset handling, timezone semantics, and device time-sync policy.
- [x] Define recording StoragePool placement, disk failover, draining, and remote-archive separation.
- [x] Define authentication, role/permission model, camera scope, media authorization, and audit.
- [x] Define configuration/SecretStore separation, envelope encryption, key rotation, and encrypted backup semantics.
- [x] Define complete-first production release policy: known product-grade capabilities ship in the first release.
- [ ] Review and refine remaining architecture decisions before implementation.

## Phase 1 — Platform foundation

- [ ] Backend project bootstrap.
- [ ] Frontend project bootstrap.
- [ ] PostgreSQL + Alembic.
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

- API + Web + PostgreSQL boot reliably.
- empty Device Center works.
- migrations are repeatable.
- no media-specific code leaks into Camera domain.

## Phase 2 — ZLMediaKit Media Plane

- [ ] Add ZLMediaKit service.
- [ ] Implement MediaPlane contract.
- [ ] Manual RTSP camera creation/probe.
- [ ] CameraClockStatus sampling for ONVIF-capable devices.
- [ ] optional monitor/manage_ntp/ignore device-time mode.
- [ ] inherit system managed-camera NTP settings with optional per-camera NTP override.
- [ ] apply/verify managed-camera NTP configuration without modifying host OS NTP service.
- [ ] device clock offset/RTT/quality health diagnostics.
- [ ] Ensure/remove stream proxy.
- [ ] per-camera source runtime state machine: streaming / degraded / reconnecting / offline.
- [ ] ZLM source registration/unregistration + pull-proxy close/error integration.
- [ ] configurable reconnect backoff/jitter and offline threshold.
- [ ] infinite/background retry while camera remains enabled.
- [ ] Stream runtime health.
- [ ] Live-session API.
- [ ] Browser WebRTC/fMP4/HLS path.
- [ ] camera/live authorization before media-session issuance.
- [ ] Live Monitor MVP.

Acceptance:

- one Camera can be added and viewed live without FastAPI decoding frames.
- media-engine restart is recoverable without losing Camera metadata.

## Phase 3 — Recording Plane

- [ ] Implement RecordingManager per-camera intent arbiter.
- [ ] RecordingIntent persistence/recovery and idempotent transitions.
- [ ] Implement RecorderBackend.
- [ ] FFmpeg consumes ZLM internal stream.
- [ ] RecordingPolicy / Recording Settings persistence and API.
- [ ] explicit schedule_timezone handling for wall-clock schedules.
- [ ] Recording Settings UI for prebuffer enable, 20s idle segment default, 5min formal segment default, and pre/post-roll.
- [ ] segment persistence.
- [ ] UTC canonical recording timestamps and database timeline indexes.
- [ ] compact human-readable local recording layout: name-id / date / name-id_date_start.mp4.
- [ ] configurable effective recording timezone for all generated path/date/time values while DB stays UTC.
- [ ] per-camera _camera.json convenience metadata for detached-disk browsing.
- [ ] staging/atomic finalize and backend object-key mapping.
- [ ] StoragePool / StoragePoolTarget persistence and default pool.
- [ ] sticky_balanced recording target selection.
- [ ] per-target health/free-space eligibility and hard reserve.
- [ ] planned safe-boundary target switch under pressure.
- [ ] mid-segment storage failover preserving RecordingSession/Intent.
- [ ] recovered-target stability hysteresis and draining mode.
- [ ] cross-day segments without midnight force-split.
- [ ] source-loss segment finalize with completion_reason = source_lost.
- [ ] post-reconnect new segment clock anchored at actual recovery time.
- [ ] preserve RecordingSession/RecordingIntent across transport outage.
- [ ] SourceConnectivityIncident persistence and gap explanation.
- [ ] recorder recovery / orphan and partial-file reconciliation.
- [ ] RetentionPolicy / RetentionClaim persistence.
- [ ] normal age-based retention worker.
- [ ] 80/85/92/96% storage-watermark health and cleanup state machine.
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
- [ ] LAN discovery.
- [ ] Device information.
- [ ] Media Profiles.
- [ ] stream selection.
- [ ] capability persistence.
- [ ] ONVIF Events.
- [ ] PTZ after Events.

Acceptance:

- no hand-written general SOAP/WSDL stack.
- ONVIF devices still map into the same Camera/MediaStream model.

## Phase 5 — Event Detection Platform

- [ ] DetectionProvider contract.
- [ ] DetectionEvent schema supporting stateful and instant lifecycle kinds.
- [ ] source_occurred_at / received_at / occurred_at timestamp provenance and clock-offset correction.
- [ ] native camera events.
- [ ] optional local lightweight motion with hysteresis + START/END hold state machine.
- [ ] pulse-only source normalization/hold timeout where required.
- [ ] optional Frigate provider.
- [ ] event timeline/filtering using DetectionEvent markers.
- [ ] structured EventLog persistence/query.
- [ ] event snapshots.

## Phase 6 — Alerting and Notifications

- [ ] AlertRule.
- [ ] AlertDelivery.
- [ ] notification worker.
- [ ] SMTP/email NotificationBackend.
- [ ] email templates for alerts/security/password reset/system health.
- [ ] Apprise adapter.
- [ ] webhook action.
- [ ] Home Assistant/integration notification actions where configured.
- [ ] delivery retry/backoff/final result history.
- [ ] cooldown/deduplication.

## Phase 7 — Storage and Cloud

- [ ] StorageTarget roles: recording_hot / archive_remote / playback_cache.
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

## Phase 10 — First-release integrations (optional to enable)

- [ ] Home Assistant REST integration.
- [ ] RecordingTrigger external automation flow.
- [ ] MQTT integration / Home Assistant MQTT Discovery.
- [ ] Home Assistant Custom Integration package.
- [ ] HIK bridge.
- [ ] GB28181 / WVP.
- [ ] TURN for remote WebRTC.
- [ ] Frigate DetectionProvider.
- [ ] advanced AI-provider adapter contract + at least one production provider.
- [ ] advanced PTZ/presets/patrol where device capability allows.

Acceptance:

- HA/MQTT remain completely optional at deployment time.
- external sensor triggers can create/update canonical RecordingTrigger sessions.
- continuous recording is annotated/promoted instead of duplicated.
- integration failure does not stop core recording, playback or storage.

## Phase 11 — Operations and scale

- [ ] SecretStore KEK rotation workflow and health UI.
- [ ] database backup + separately protected keyring recovery procedure.
- [ ] normal support/config export with secrets excluded.
- [ ] privileged portable encrypted backup/restore including secrets.
- [ ] restore diagnostics for missing/wrong keyring and unavailable credentials.
- [ ] metrics.
- [ ] user/role/camera-scope administration UI.
- [ ] audit UI.
- [ ] backup/restore.
- [ ] upgrade/rollback.
- [ ] long-duration multi-camera acceptance.
- [ ] evaluate multi-host media/storage topology.

## Out of current product scope

These are intentionally outside the first production release because mature components already satisfy the need or the capability belongs to a different deployment class:

- hand-written general ONVIF SOAP/WSDL stack;
- a custom WebRTC server replacing ZLMediaKit;
- custom generic cloud-drive implementations replacing S3/rclone/OpenList adapters;
- making Frigate a competing NVR/source-of-truth database;
- Kubernetes-first deployment;
- distributed multi-site/multi-host clustering/federation.

See [Spec 0013 — First Production Release Scope and Completeness Policy](specs/0013-first-production-release-scope.md).
