# zero-nvr V2 Roadmap

This roadmap describes sequencing, not fixed release dates.

## Phase 0 — Repository and architecture baseline

- [x] Initialize zero-nvr repository.
- [x] Define control-plane / device-plane / media-plane ownership.
- [x] Define reuse-first integration policy.
- [x] Define first canonical domain model.
- [ ] Review and refine architecture decisions before implementation.

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
- [ ] RecordingPolicy.
- [ ] segment persistence.
- [ ] recorder recovery.
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
- [ ] DetectionEvent schema.
- [ ] native camera events.
- [ ] optional local lightweight motion.
- [ ] optional Frigate provider.
- [ ] event timeline/filtering.
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

- [ ] segment promotion.
- [ ] pre-roll.
- [ ] post-roll.
- [ ] event-to-segment links.
- [ ] hybrid recording policy.

## Phase 10 — Advanced integrations

- [ ] HIK bridge.
- [ ] GB28181 / WVP.
- [ ] TURN for remote WebRTC.
- [ ] advanced AI providers.
- [ ] advanced PTZ/presets.

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
