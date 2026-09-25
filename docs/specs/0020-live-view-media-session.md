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
- camera assignment/layout state is separate from playback state: opening the
  Live page or restoring a saved layout does not automatically establish media
  sessions; operators explicitly start/pause one tile or all visible tiles;
- stopping, hiding, switching, or superseding a tile invalidates that playback
  attempt; stale asynchronous WebRTC work must not continue into WHEP, HLS
  fallback, compatibility transcode, or later descriptor attachment;
- camera pulls use ZLMediaKit `addStreamProxy.auto_close` together with
  `mp4_as_player`: idle streams close after ZLM's no-reader delay, while an
  active ZLM MP4 recorder counts as a reader and therefore keeps the recording
  source alive; this avoids zero-nvr viewer refcounts and also lets a RECORD-
  capable profile release when neither recording nor live playback is active;
- live setup/playback failures show a sanitized actionable reason in the tile,
  preserving backend error code/request ID and WebRTC/HLS fallback context
  without exposing media URLs, tokens, or credentials;
- long-running live playback renews the same authorized MediaSession before
  expiry instead of tearing down and rebuilding WHEP/HLS every 30 minutes;
  session-bound ZLM playback URLs continue to require a valid signature, but
  their embedded timestamp does not force a player reload while that exact
  MediaSession remains active; revocation/expiry of the MediaSession immediately
  makes the old URL unauthorized, while non-session VOD/media grants keep their
  normal strict timestamp expiry;
- the initial `/live` descriptor carries the authorized short-lived
  ICE/TURN server bundle so first playback does not require a separate
  `/live/ice` round trip; the legacy ICE endpoint remains available for
  compatibility/explicit refresh, and TURN configuration failure is reported
  non-blockingly so direct LAN WebRTC can still proceed;
- LAN WebRTC caps host-only ICE gathering aggressively while TURN-backed
  sessions retain the longer gathering window needed for relay candidates;
  the browser keeps non-trickle SDP completeness but uses a one-entry ICE
  candidate pool to pre-gather candidates and reduce time spent in that phase;
- only the initial `/live` descriptor request resolves credentials for and
  ensures the selected profile's ZLM source runtime; before returning the
  descriptor it briefly waits for ZLM's allow-listed media probe to report a
  ready video track, whether the pull was just created or was already online;
  this prevents the browser's first WHEP/HLS attempt from racing the gap
  between stream registration and video-track readiness; the bounded wait
  reuses ZLM state and does not introduce a second reconnect engine;
  the issued media session is then bound to that exact profile/purpose;
  unrelated bound profiles are not decrypted/resolved on the live-start
  critical path;
  authorized follow-up WHEP/diagnostic/compatibility requests reuse the
  session-bound deterministic stream reference instead of repeating ZLM online
  checks or accepting a later quality parameter as a profile switch; browser
  ICE configuration fetch overlaps local SDP offer creation;
- a transport is not considered successfully attached until the browser
  renders a first video frame; WebRTC first-frame timeout or connection failure
  before that first frame falls back to HLS, while a WebRTC connection failure
  after successful attachment uses the normal reconnect path; when the original
  HLS path fails before its first frame, the browser makes one bounded attempt
  to use the existing H.264 compatibility derivative before surfacing failure
  and reconnecting; this runtime fallback does not recursively transcode;
  WebRTC does not call `video.play()` until its remote track has attached a
  media source, so the short gap between `setRemoteDescription()` and
  `ontrack` cannot be misclassified as a playback-start failure; HLS likewise
  waits until its URL/MediaSource is attached before requesting playback;
  first-frame latency telemetry is recorded at this same decoded/rendered-frame
  boundary rather than at the earlier HTMLMediaElement `playing` event;
- focused live diagnostics break startup latency into descriptor API, ICE
  gathering, WHEP negotiation, and answer-to-rendered-frame phases without
  adding requests; these measurements are observational only and do not create
  another media-runtime state machine;
- first-frame timeout performs an on-demand, permission-gated ZLM media
  diagnostic that distinguishes source offline, missing video track, video
  track not ready, and browser-side delivery/decoding failure; diagnostics
  expose only allow-listed track metadata and never source URLs or credentials;
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
   - plays without FFmpeg transcode;
   - a successful session must produce a decoded first video frame;
   - WebRTC with no first frame falls back to HLS before surfacing failure.

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
