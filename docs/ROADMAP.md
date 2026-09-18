# zero-nvr V2 Roadmap

This roadmap describes sequencing, not fixed release dates.

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
- [ ] Review and refine remaining architecture decisions before implementation.

## Phase 1 — Platform foundation

- [ ] Backend project bootstrap.
- [ ] Frontend project bootstrap.
- [ ] PostgreSQL + Alembic.
- [ ] Configuration/secrets model.
- [ ] Structured logging and health/readiness.
- [ ] Base Camera / CameraConnection schema.
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
- [ ] Ensure/remove stream proxy.
- [ ] Stream runtime health.
- [ ] Live-session API.
- [ ] Browser WebRTC/fMP4/HLS path.
- [ ] Live Monitor MVP.

Acceptance:

- one Camera can be added and viewed live without FastAPI decoding frames.
- media-engine restart is recoverable without losing Camera metadata.

## Phase 3 — Recording Plane

- [ ] Implement RecorderBackend.
- [ ] FFmpeg consumes ZLM internal stream.
- [ ] RecordingPolicy / Recording Settings persistence and API.
- [ ] Recording Settings UI for prebuffer enable, 20s idle segment default, 5min formal segment default, and pre/post-roll.
- [ ] segment persistence.
- [ ] UTC canonical recording timestamps and database timeline indexes.
- [ ] compact human-readable local recording layout: name-id / date / name-id_date_start.mp4.
- [ ] configurable effective recording timezone for all generated path/date/time values while DB stays UTC.
- [ ] per-camera _camera.json convenience metadata for detached-disk browsing.
- [ ] staging/atomic finalize and backend object-key mapping.
- [ ] cross-day segments without midnight force-split.
- [ ] recorder recovery / orphan and partial-file reconciliation.
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
- [ ] native camera events.
- [ ] optional local lightweight motion with hysteresis + START/END hold state machine.
- [ ] pulse-only source normalization/hold timeout where required.
- [ ] optional Frigate provider.
- [ ] event timeline/filtering using DetectionEvent markers.
- [ ] structured EventLog persistence/query.
- [ ] event snapshots.

## Phase 6 — Alerting

- [ ] AlertRule.
- [ ] AlertDelivery.
- [ ] notification worker.
- [ ] Apprise adapter.
- [ ] webhook action.
- [ ] cooldown/deduplication.

## Phase 7 — Storage and Cloud

- [ ] StorageTarget / StorageObject.
- [ ] local retention.
- [ ] S3 adapter.
- [ ] upload state machine.
- [ ] remote verification.
- [ ] rclone adapter.
- [ ] OpenList adapter.
- [ ] safe local purge.

## Phase 8 — Historical Playback

- [ ] timeline query API.
- [ ] local playback.
- [ ] cross-segment continuation.
- [ ] remote object resolver.
- [ ] playback cache.
- [ ] cloud-only playback.
- [ ] export.

## Phase 9 — Event Recording

- [ ] RecordingSession lifecycle.
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

## Phase 10 — Optional integrations

- [ ] Home Assistant REST integration.
- [ ] RecordingTrigger external automation flow.
- [ ] Optional MQTT integration / Home Assistant MQTT Discovery.
- [ ] Future Home Assistant Custom Integration.
- [ ] HIK bridge.
- [ ] GB28181 / WVP.
- [ ] TURN for remote WebRTC.
- [ ] advanced AI providers.
- [ ] advanced PTZ/presets.

Acceptance:

- HA/MQTT remain completely optional at deployment time.
- external sensor triggers can create/update canonical RecordingTrigger sessions.
- continuous recording is annotated/promoted instead of duplicated.
- integration failure does not stop core recording, playback or storage.

## Phase 11 — Operations and scale

- [ ] metrics.
- [ ] audit UI.
- [ ] backup/restore.
- [ ] upgrade/rollback.
- [ ] long-duration multi-camera acceptance.
- [ ] evaluate multi-host media/storage topology.

## Explicitly deferred

Until the relevant phase:

- do not hand-write ONVIF SOAP;
- do not build a custom WebRTC server;
- do not build generic cloud-drive clients;
- do not make Frigate the main NVR database;
- do not optimize for Kubernetes or distributed clustering before the single-host product is solid.
