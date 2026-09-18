# Plan 01 — ZLMediaKit Media Plane

Status: **first-pass plan; refine before implementation**

## Objective

Make ZLMediaKit the standard live-media engine while zero-nvr remains authoritative for Camera and MediaStream state.

## Scope

This phase includes:

- ZLM deployment;
- MediaPlane contract implementation;
- Manual RTSP source;
- stable stream mapping;
- runtime reconciliation;
- live-session API;
- browser live preview.

This phase does not include:

- ONVIF;
- AI;
- cloud storage;
- PTZ;
- replacing FFmpeg recording;
- advanced multi-camera wall optimization.

## Task 1 — ZLM service

Add ZLMediaKit to development Compose.

Requirements:

- internal control/API access from zero-nvr;
- browser-required media ports only;
- no credentials baked into repository config;
- health/readiness check;
- persistent config only where actually necessary.

## Task 2 — MediaPlane contract

Define DTOs roughly around:

```text
MediaSource
MediaStreamKey
MediaRuntimeStatus
LivePlayUrls
```

Operations:

```text
ensure_stream(source)
remove_stream(stream_key)
get_status(stream_key)
get_live_urls(stream_key)
snapshot(stream_key)
health()
```

## Task 3 — ZlmMediaPlane

Wrap ZLM REST/WebHook behavior.

Business services must not call raw ZLM endpoints directly.

Map Camera/MediaStream to stable internal stream keys.

Example conceptual key:

```text
camera/{camera_id}/main
```

Exact ZLM app/stream/vhost mapping is an implementation detail.

## Task 4 — Manual RTSP Camera

Support the first real DeviceAdapter/connection:

```text
manual_rtsp
```

Input:

- host/port;
- username/password;
- main stream path.

Generate a credential-bearing source URI only inside trusted runtime boundaries.

Never expose it in public API responses.

## Task 5 — Reconciliation

On runtime start:

1. query enabled Cameras;
2. resolve current MediaStreams;
3. ensure required ZLM proxies;
4. remove/reconcile stale managed streams safely.

A ZLM restart must not require Camera recreation.

## Task 6 — Live session

FastAPI returns an authorized live-session DTO.

Candidate protocols:

1. WebRTC;
2. HTTP-fMP4;
3. HLS fallback.

The browser receives media URLs/session metadata but does not receive Camera source credentials.

## Task 7 — Frontend Live MVP

Device Center:

- open Live action.

Live view:

- connection state;
- selected protocol;
- retry/fallback;
- no JPEG-over-WebSocket decoding pipeline.

## Task 8 — WebHook integration

Use ZLM WebHooks where they improve runtime state:

- stream registered/unregistered;
- optional reader/runtime events.

WebHooks update transient runtime status, not Camera business identity.

## Tests

At minimum:

- MediaPlane fake contract tests;
- ZLM API adapter tests with mocked HTTP;
- credential redaction;
- reconciliation idempotency;
- Camera disabled removes desired stream;
- ZLM unavailable degrades live capability without corrupting Camera state;
- Compose smoke with ZLM health;
- browser/live API contract tests.

## Exit criteria

- Manual RTSP Camera can be added.
- zero-nvr ensures one managed ZLM stream.
- browser can view it live without FastAPI decoding frames.
- restarting ZLM is recoverable.
- disabling the Camera tears down managed live media.
- no raw ZLM model becomes a zero-nvr domain identity.

## Follow-up

Plan 02 should add FFmpeg RecorderBackend consuming the ZLM internal stream while preserving the MediaPlane boundary.
