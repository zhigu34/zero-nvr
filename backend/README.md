# Backend

The backend is the **zero-nvr product/control plane**, implemented as a FastAPI modular monolith plus a Huey worker.

## Owns

- authentication / RBAC / camera scope;
- Camera / Device / CameraStreamProfile / CameraStreamBinding;
- recording policy and RecordingTrigger arbitration;
- RecordingSegment / RecordingLocation catalog;
- Timeline / Gap projection and PlaybackResolver;
- canonical Event;
- AlertPolicy / Alert / NotificationDelivery;
- StorageTarget / retention / protection policy;
- Export;
- backup product state;
- settings, health aggregation, and AuditEvent;
- reconciliation across external components.

## Does not own

- RTSP / WebRTC / HLS server implementation;
- source reconnect engine;
- normal MP4 recorder;
- AI inference/tracking;
- ONVIF SOAP/WSDL implementation;
- cloud-drive protocols;
- RAID/JBOD/filesystem pooling;
- generic task queue;
- notification provider implementations;
- backup repository engine;
- monitoring TSDB.

## Main integrations

~~~text
ZLMediaKit  -> media / recorder / VOD
ONVIF libs  -> camera discovery/control
Frigate     -> optional AI
rclone      -> archive/restore
Apprise     -> notification delivery
restic      -> system backup repository
FFmpeg      -> derived media only
~~~

## Module boundary

See:

- [V1 API / Module Freeze](../docs/plans/03-v1-api-module-freeze.md)
- [V1 Schema Freeze](../docs/plans/02-v1-schema-freeze.md)
- [Project Baseline](../docs/PROJECT_BASELINE.md)

Broad backend implementation should not begin until the relevant design-freeze POC assumptions have evidence, although safe platform/bootstrap work may proceed.
