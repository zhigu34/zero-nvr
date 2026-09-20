# Plan 01 — ZLMediaKit Media Plane

Status: **blocked on relevant design-freeze POCs for final implementation details**

## Goal

Integrate ZLMediaKit as the camera-facing media bus and normal recording/VOD authority.

This plan must not introduce a parallel FFmpeg recorder or a second RTSP reconnect engine.

## Target path

```text
Camera main/sub
   -> ZLMediaKit
       ├─ Live
       ├─ ZLM MP4/fMP4 Recorder
       ├─ VOD
       ├─ Snapshot
       └─ internal stream -> optional Frigate
```

## Task 1 — ZLM service

Provide a version-pinned ZLM Compose service.

Validate:

- health/readiness;
- internal API secret/config;
- recording root mount;
- network ports required by selected live protocols;
- hooks back to zero-nvr;
- configurable recorder segment target;
- version reporting.

Do not expose ZLM administration directly to the browser.

## Task 2 — ZlmAdapter / MediaPlane

Implement a thin adapter for supported operations such as:

- ensure/remove camera stream proxy;
- query media registration/runtime state;
- obtain live playback descriptors/identifiers;
- start/stop/query ZLM recording where policy requires explicit control;
- snapshot;
- VOD resolution;
- consume supported hooks.

Business services call the adapter, not raw ZLM HTTP endpoints.

The adapter does not:

- decode video;
- implement RTSP;
- schedule packet-level reconnect;
- decide product recording policy.

## Task 3 — Camera stream identity

Map:

```text
Camera
+ CameraStreamProfile
+ CameraStreamBinding
-> stable ZLM app/stream identifiers
```

Purpose bindings include:

- RECORD;
- LIVE_HIGH;
- LIVE_LOW;
- AI_DETECT;
- SNAPSHOT.

Camera credentials stay server-side/SecretStore.

## Task 4 — Stream onboarding

For ONVIF cameras:

```text
ONVIF discovery/profile URI
-> zero-nvr
-> ZLM pull/proxy
-> actual media verification
```

Manual RTSP follows the same ZLM path.

Avoid each downstream consumer pulling the camera independently.

## Task 5 — Live descriptor

Implement zero-nvr API resolution that:

- authorizes camera scope;
- chooses LIVE_LOW/LIVE_HIGH;
- confirms ZLM media availability;
- returns short-lived player descriptor;
- provides fallback protocol hints;
- never returns camera RTSP credentials.

Frontend uses player adapters.

No JPEG-over-WebSocket custom streaming pipeline.

## Task 6 — ZLM recording

Normal continuous/scheduled recording uses ZLM recorder.

Validate through design-freeze POCs:

- segment finalization;
- actual start/end/duration metadata;
- `on_record_mp4`;
- fMP4 candidate behavior;
- control-plane restart independence;
- recovery reconciliation.

FFmpeg is not the normal recorder.

## Task 7 — Recording hook

`on_record_mp4` normal path:

```text
ZLM finalized file
-> protected internal hook
-> validate media identity/path
-> UPSERT/insert RecordingSegment
-> create/update local RecordingLocation
-> enqueue downstream archive/retention work
```

Hook processing must be idempotent.

A lost hook is recovered by reconciliation.

## Task 8 — ZLM runtime recovery boundary

Use ZLM-native source pull/reconnect behavior.

zero-nvr observes:

- media register/unregister;
- recorder state;
- ZLM health;
- finalized recording hooks.

Product health projects ONLINE/DEGRADED/OFFLINE without owning a competing RTSP retry engine.

## Task 9 — VOD / seek

Validate:

- local recording playback through ZLM;
- segment seek;
- wall-clock -> segment/media offset mapping;
- gap behavior;
- restored remote cache files through the same VOD path.

This is part of the design-freeze gate.

## Task 10 — Snapshot

Use ZLM snapshot capability for live/manual current snapshots where appropriate.

Historical arbitrary-time snapshots use PlaybackResolver + FFmpeg frame extraction only as fallback/derived work.

## Acceptance

This media-plane slice passes when:

- main/sub camera streams are pulled through ZLM;
- browsers consume zero-nvr-authorized ZLM playback, not camera URLs;
- one camera connection per configured original stream is observed in the sharing POC;
- ZLM normal recording produces indexed segments;
- FFmpeg is not running as a permanent recorder;
- ZLM reconnect behavior is used instead of custom RTSP reconnect code;
- API restart does not deliberately stop an already-running ZLM recorder where architecture permits;
- lost-hook reconciliation restores catalog state;
- VOD seek/timeline behavior meets the POC criteria.
