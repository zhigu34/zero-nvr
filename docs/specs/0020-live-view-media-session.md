# Spec 0020 — Live View, Media Sessions, Compatibility, and Audio

Status: **accepted**

## Goal

Define a lightweight live-view model around ZLMediaKit without turning zero-nvr into a second streaming server.

Core rule:

> ZLMediaKit owns media delivery. zero-nvr authorizes a live session, selects the appropriate camera stream and playback descriptor, and only invokes FFmpeg when compatibility genuinely requires derived media.

See [Project Baseline](../PROJECT_BASELINE.md).

## Stream-purpose model

Live view does not select raw camera URLs directly.

Use CameraStreamBinding:

```text
LIVE_HIGH -> usually primary/main stream
LIVE_LOW  -> usually secondary/sub stream
AUDIO     -> supported source when available
```

Typical behavior:

- grid tiles use LIVE_LOW;
- focused/fullscreen camera uses LIVE_HIGH;
- switching quality changes the zero-nvr/ZLM playback descriptor, not camera identity;
- recording remains independent through RECORD binding.

## Media path

```text
Camera
  -> ZLMediaKit
      -> live protocols
      -> browser/player adapter
```

The browser never receives camera credentials and does not administer ZLM directly.

## Live session authorization

A live request goes through zero-nvr:

```text
user
-> /api/v1/cameras/{id}/live
-> camera:view + camera scope check
-> choose LIVE_LOW/LIVE_HIGH
-> resolve ZLM media
-> return short-lived playback descriptor
```

Descriptor may contain:

- protocol;
- URL/token;
- expiration;
- codec/container hints;
- fallback options;
- audio availability;
- compatibility notes.

Permanent credential-bearing camera RTSP URLs are never returned.

## Player adapters

Frontend player handling is adapter-based.

V1 candidates:

- WebRTC through ZLM;
- native browser MP4/fMP4/HLS where supported;
- Jessibuca or another mature player for browser/codec combinations that need it.

The backend returns capabilities/descriptors; the frontend does not hard-code one global player path.

## Protocol preference

A practical preference may be:

```text
WebRTC
-> browser-compatible HTTP/fMP4/HLS path
-> compatibility player/derived stream when required
```

The exact choice is based on browser/media capability rather than a universal fixed order.

WebRTC carries media. Application status/events normally use HTTP/SSE; zero-nvr does not introduce a general WebSocket dependency merely for live video.

## Browser/codec compatibility

Recording codec does not need to be changed just because one browser cannot decode it.

Preferred order:

1. use an already compatible camera stream profile;
2. use a mature player path that supports the codec;
3. only then create a bounded FFmpeg compatibility derivative.

Do not permanently transcode every camera.

## On-demand compatibility transcode

FFmpeg may create a live compatibility derivative when needed.

Requirements:

- only on demand;
- bounded global/per-host capacity;
- may be shared by viewers requesting the same compatible derivative;
- idle derivatives are cleaned up;
- failure/capacity exhaustion does not affect recording;
- hardware acceleration may be used when actually available;
- CPU fallback must have resource limits.

This is derived media, not normal recording authority.

No durable database entity is required for short-lived live transcode processes unless implementation proves a need.

## Quality switching

Frontend behavior:

- multi-grid defaults to LIVE_LOW;
- focus/fullscreen may promote to LIVE_HIGH;
- demotion returns to LIVE_LOW;
- use debounce/hysteresis to avoid rapid toggling.

Network-aware automatic quality may be added when it remains simple and explainable; manual high/low switching is sufficient for the baseline.

## Audio playback

When supported by the selected source/player:

- grid is muted by default;
- focused camera can enable audio;
- audio failure does not fail video or recording;
- browser autoplay restrictions are handled explicitly.

## Snapshot

Manual live snapshot priority:

```text
ZLM getSnap / mature snapshot API
-> fallback only when necessary
```

Do not expose a permanent camera snapshot URL with credentials.

## TURN

coturn is an optional deployment capability for remote WebRTC through NAT/firewalls.

It is **not** required for a LAN-only V1 deployment and does not block the release.

When enabled:

- TURN credentials are short-lived;
- shared secrets stay server-side/SecretStore;
- credentials are issued only after camera authorization;
- TURN failure affects remote WebRTC capability, not recording.

If a deployment already has compatible TURN infrastructure, External mode/configuration should be possible rather than forcing another coturn service.

Implemented deployment modes:

- default/LAN: TURN disabled and no coturn container is pulled or started;
- managed: `./deploy.sh feature enable turn` enables the optional coturn Compose profile, generates the shared secret, writes the managed coturn config, and enables short-lived credential issuance in the API;
- external: operators set TURN URL(s) plus the shared secret without enabling the managed profile.

Managed TURN keeps a bounded relay port range and can advertise an explicit external IP for NAT deployments. The browser requests ICE servers only after the user has an authorized Camera MediaSession; failure to obtain TURN credentials falls back to direct WebRTC and never affects recording.

## Health

Live health is capability-specific:

```text
media source
ZLM
selected playback protocol
optional compatibility transcode
optional TURN
optional audio
```

Examples:

- recording OK / WebRTC unavailable / HLS fallback available;
- live video OK / audio unsupported;
- LAN live OK / remote TURN unavailable.

## UI

Live page baseline:

- 1/4/9/16 layouts;
- LIVE_LOW in grid;
- LIVE_HIGH on focus/fullscreen;
- camera name/status;
- mute/audio control where supported;
- snapshot;
- PTZ drawer/overlay when authorized;
- quality/manual protocol diagnostics in advanced view;
- live setup/playback failures show a sanitized actionable reason in the tile,
  preserving backend error code/request ID and WebRTC/HLS fallback context
  without exposing media URLs, tokens, or credentials;
- minimal overlay clutter by default.

## Acceptance tests

1. Four-camera grid:
   - uses LIVE_LOW bindings;
   - does not create extra direct RTSP pulls from browsers.

2. Focus camera:
   - promotes to LIVE_HIGH;
   - returning to grid can demote cleanly.

3. Authorization:
   - unauthorized camera produces no playable descriptor;
   - camera credentials are never exposed.

4. Browser-compatible H.264:
   - plays without FFmpeg transcode.

5. Incompatible codec:
   - uses alternate source/player or bounded on-demand derivative;
   - recording is unaffected by transcode failure.

6. ZLM restart:
   - live session can re-resolve after service recovery;
   - Camera identity/configuration is unchanged.

7. Audio:
   - audio can fail independently from video.

8. TURN disabled:
   - LAN deployment works normally without coturn.

9. TURN enabled:
   - credentials are short-lived and permission-gated.


## Invariants

1. ZLM is the live media server.
2. Browsers do not receive camera credentials.
3. Frontend calls zero-nvr for authorization/resolution rather than administering ZLM.
4. Grid and focused views use stream-purpose bindings rather than raw profile assumptions.
5. FFmpeg live transcode is on-demand derived media only.
6. Live transcode/TURN failure never stops recording.
7. TURN is capability-dependent and non-blocking for V1.
8. Application WebSocket is not required for video transport.
