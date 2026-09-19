# Spec 0020 — Live View, Media Sessions, Adaptive Quality, TURN, and Talk

Status: **accepted**

## Goal

Define the complete first-production-release live-view architecture.

Core rule:

> Live viewing is an authorized short-lived MediaSession that resolves the best playable transport and stream role for the current browser, viewport, network, and camera capabilities. Recording source quality remains independent from browser playback constraints.

This specification covers:

- single-camera and multi-camera live view;
- MediaSession authorization and lifecycle;
- live_preview/live_main role switching;
- WebRTC/fMP4/HLS transport selection and fallback;
- H.264/H.265 browser compatibility;
- adaptive quality and bandwidth behavior;
- on-demand transcode;
- STUN/TURN/coturn;
- audio playback and two-way talk;
- snapshots, PTZ overlay, reconnect, privacy/security, health, and UI.

## Ownership boundaries

```text
Browser Live View
      ↓
FastAPI LiveSessionService
      ↓ authorization + capability decision
MediaSession
      ↓
MediaPlane
      ↓
ZLMediaKit
      ↓
Camera MediaStream runtime
```

FastAPI owns authorization, session policy, camera scope, transport decision metadata, and audit/security boundaries.

ZLMediaKit owns transient media protocol delivery and RTP/WebRTC/fMP4/HLS runtime.

Camera credentials are never sent to the browser.

## MediaSession

Conceptual model:

```text
MediaSession
  id
  principal_id
  camera_id
  requested_purpose       grid | focus | fullscreen | popout | talk
  requested_quality       auto | preview | main
  effective_stream_role
  transport               webrtc | fmp4 | hls
  source_codec
  delivery_codec
  transcoded
  runtime_generation
  issued_at
  expires_at
  last_seen_at
  ended_at
  end_reason
```

MediaSession is short-lived authorization/runtime metadata, not a permanent media URL.

Session state may be persisted or ephemeral depending on revocation/observability needs, but server-side revocation must be possible for active sessions where practical.

## Authorization

Opening live video requires:

```text
camera.view
AND live.view
AND camera inside effective scope
```

Talk additionally requires:

```text
camera.talk
```

PTZ remains separately gated by `camera.ptz`.

Every transport URL/token issued from a MediaSession is:

- short lived;
- camera/session scoped;
- transport scoped where practical;
- free of source credentials;
- invalid after session expiry/revocation.

Do not expose ZLMediaKit admin/API secrets to the browser.

## Browser capability report

The frontend reports playback capabilities at session creation and when materially changed.

Conceptual report:

```text
BrowserMediaCapabilities
  webrtc
  mse_fmp4
  hls_native
  h264
  h265
  opus
  aac
  microphone
  secure_context
  viewport_width
  viewport_height
  device_pixel_ratio
```

Capability detection may use browser APIs such as codec support/media capabilities and WebRTC capability negotiation.

User-agent string alone is never authoritative.

## Transport preference

Default preference:

```text
1. WebRTC
2. fMP4
3. HLS
```

but only when the selected transport/codec combination is actually supported.

### WebRTC

Preferred for low-latency interactive live viewing and talk.

ZLMediaKit provides the media runtime/signaling implementation behind MediaPlane.

WebRTC session setup is brokered through zero-nvr so authorization occurs before signaling/media access.

### fMP4

Preferred non-WebRTC fallback where the browser can consume the delivery codec/container.

It is useful for live viewing when WebRTC is blocked/unsupported and lower latency than segment-heavy HLS is still desirable.

### HLS

Compatibility/fallback transport.

HLS has higher latency and is not used for PTZ/talk-interactive UX when a lower-latency transport is available.

## Transport fallback

Session establishment may fall back automatically:

```text
WebRTC failed during bounded setup
  ↓
fMP4 if supported
  ↓
HLS if supported
```

Fallback reason is observable:

```text
ice_failed
turn_failed
codec_unsupported
signaling_failed
mse_unsupported
network_timeout
```

Do not loop rapidly between transports.

## Stream role policy

Use canonical roles from Spec 0018:

```text
live_preview
live_main
```

Grid tiles default to `live_preview`.

Focused/fullscreen/popout views prefer `live_main`.

Recording continues on the independent `recording` role.

## Multi-camera grid

Grid layout may include many Cameras, but zero-nvr must avoid pulling main streams unnecessarily.

Initial policy:

```text
visible tile
  -> live_preview

focused tile
  -> live_main when useful

offscreen/hidden tile
  -> pause/close after grace
```

Intersection/visibility state from the frontend may be used as a hint, but backend session limits remain authoritative.

## Focus promotion

When a user focuses/maximizes a tile:

```text
preview session
  ↓
request main-quality MediaSession
  ↓
new stream reaches playable state
  ↓
crossfade/swap
  ↓
old preview session retained briefly or released
```

Promotion should avoid a blank frame where practical.

Demotion from main to preview uses hysteresis/grace so rapid UI toggling does not thrash camera/ZLM runtimes.

## Viewport-aware quality

`auto` quality considers:

- viewport dimensions;
- device pixel ratio;
- tile focus state;
- source profile dimensions/bitrate;
- measured network/session health;
- configured user/system bandwidth policy.

A 4K source should not automatically be used for a 320×180 grid tile.

## Adaptive quality

Adaptive quality is primarily profile selection, not mandatory transcoding.

```text
good network / large focused view
  -> live_main

constrained network / grid
  -> live_preview
```

WebRTC congestion control can improve transport behavior, but a fixed-bitrate RTSP camera source cannot be assumed to support arbitrary bitrate adaptation.

Therefore source-profile switching is the primary camera-side adaptation mechanism.

## Switching hysteresis

Automatic quality changes use hysteresis:

- do not switch on one transient packet-loss sample;
- require sustained degradation before downgrade;
- require sustained recovery before promotion;
- rate-limit role/transport switches.

This prevents oscillation between main/preview.

## LiveSession statistics

Session telemetry may include:

```text
transport
stream_role
source_codec
delivery_codec
bitrate
packet_loss
rtt
jitter
frames_decoded
frames_dropped
resolution
first_frame_ms
reconnect_count
turn_relayed
```

Telemetry is sampled/aggregated; do not persist every WebRTC stats frame.

## H.265 / HEVC policy

H.265 support is capability-dependent.

Rules:

- H.265 recording may remain native even when the browser cannot play it;
- never globally change the recording profile merely to satisfy one browser;
- direct H.265 live delivery is attempted only when browser + transport capability proves support;
- if `live_preview`/`live_main` has an H.264 alternative, prefer it for broad browser compatibility;
- if no compatible source profile exists, use on-demand live transcode when enabled/capable;
- otherwise surface a clear unsupported-codec state and fallback options.

## H.264 WebRTC constraints

When converting/proxying H.264 into browser WebRTC, MediaPlane must verify WebRTC-compatible H.264 characteristics.

Streams with incompatible B-frame/profile behavior may require an alternate source profile or transcode path.

Do not assume every RTSP H.264 bitstream is directly WebRTC-playable.

## On-demand transcode

Transcoding exists for live compatibility, not as the default ingest architecture.

Conceptual runtime:

```text
camera source
  ↓
ZLM / internal source
  ↓
TranscodeManager
  ↓
browser-compatible derivative
  ↓
ZLM delivery
```

Typical conversions:

```text
H.265 -> H.264
incompatible H.264 -> browser-compatible H.264
G.711/AAC -> Opus for WebRTC audio where required
```

## Shared transcode derivatives

Do not spawn one FFmpeg transcoder per viewer when viewers can share the same derivative.

Transcode key:

```text
camera_id
source_profile_id
target_codec
target_resolution
target_bitrate_class
audio_policy
```

One derivative may serve multiple authorized MediaSessions through ZLM.

Reference-count/idle-TTL shutdown is used.

## Transcode limits

System settings expose resource limits:

```text
max_live_transcodes
max_transcode_pixels_per_second
preferred_acceleration
cpu_fallback_enabled
transcode_idle_ttl
```

Hardware acceleration may use available platform support such as VAAPI/QSV/NVENC/VideoToolbox through FFmpeg, but zero-nvr must probe actual capability rather than assume a specific GPU.

If capacity is exhausted:

- prefer compatible lower source profile;
- otherwise return `transcode_capacity_exhausted`;
- do not destabilize recording workers to satisfy live transcoding.

Recording correctness has priority over optional live transcode load.

## Live transport selection

Conceptual resolver:

```text
LivePlaybackResolver
  input:
    browser capabilities
    camera live profiles
    network/session hints
    transcode capacity
    server transport health

  output:
    effective stream role
    transport
    source profile
    delivery codec
    transcode plan
    fallback plan
```

The resolver returns an explanation for diagnostics/UI.

## STUN/TURN

Remote WebRTC uses ICE with configured STUN/TURN.

coturn is the default TURN implementation.

TURN is optional to enable for LAN-only deployments but implemented in the first production release.

## TURN credentials

Do not expose a permanent static TURN username/password in frontend configuration.

Preferred pattern:

```text
authenticated zero-nvr MediaSession
  ↓
issue short-lived TURN credentials
  ↓
browser ICE config
```

Use coturn's supported authenticated/REST-style shared-secret mechanism or equivalent short-lived credential generation.

TURN shared secret is stored in SecretStore.

## TURN network modes

Support:

```text
STUN/direct ICE
TURN UDP relay
TURN TCP relay
TURN TLS where configured
```

UI/health shows whether a session is direct or relayed.

TURN relay bandwidth is monitored because it may become the dominant remote-view traffic path.

## ICE privacy/security

- MediaSession authorization occurs before issuing ICE/TURN credentials;
- TURN credentials are short lived;
- TURN realm/shared secret is not exposed through ordinary APIs;
- relay allocation/session limits are enforced;
- rate limiting protects signaling/session creation;
- remote media URLs/tokens expire.

## Secure context

Browser microphone/WebRTC/talk features require appropriate secure-origin behavior.

Production remote access should use HTTPS/WSS with valid TLS.

The UI diagnoses insecure-context limitations rather than silently failing microphone/WebRTC functions.

## Audio playback

LiveSession independently negotiates video and audio.

Audio may be:

```text
disabled
listen_only
listen_and_talk
```

Grid view defaults to muted audio to avoid mixing many camera feeds.

Focused camera may explicitly enable audio.

Only one camera audio stream is foreground by default unless the user deliberately enables mixing.

## Audio codec handling

Source audio codec and browser/WebRTC delivery codec are separate.

For WebRTC, Opus is preferred when transcoding is required.

Unsupported source audio must not cause video playback to fail; video-only fallback remains available.

## Two-way talk

Talk is modeled separately from ordinary live viewing.

```text
browser microphone
  ↓
authorized TalkSession
  ↓
WebRTC uplink / MediaPlane
  ↓
TalkBackend
  ↓
camera/device audio backchannel
```

TalkBackend implementations may use:

- ONVIF/RTSP backchannel where supported;
- HIK/vendor SDK bridge;
- GB28181/WVP voice path;
- other adapter-specific talk mechanisms.

ZLMediaKit may terminate/bridge the browser-side WebRTC media, but zero-nvr DeviceAdapter/TalkBackend owns camera-specific backchannel capability.

## TalkSession

Conceptual model:

```text
TalkSession
  id
  media_session_id
  principal_id
  camera_id
  backend
  codec
  started_at
  last_seen_at
  ended_at
  end_reason
```

TalkSession is short lived and requires `camera.talk` plus camera scope.

## Talk concurrency

Default per-camera policy:

```text
one active talker
```

Attempting a second talk session returns busy unless an explicit supported mixing policy exists.

UI shows who/that another session holds the talk channel without leaking unnecessary identity details.

Stale talk leases expire automatically.

## Push-to-talk and duplex

UI supports:

```text
push_to_talk
full_duplex where device/backend supports it
```

Push-to-talk is the safe default for devices whose backchannel behavior is uncertain or half-duplex.

Echo cancellation/noise suppression preferences are applied on browser microphone capture where appropriate.

## Talk failure isolation

Talk failure must never terminate video viewing or recording.

Video session and TalkSession are separate lifecycles.

## Snapshot

Live view supports an authorized snapshot action.

Priority:

```text
device-native snapshot if appropriate
or
MediaPlane current-frame snapshot
```

Snapshot respects `camera.view`/camera scope and export/download policy when persisting/downloading artifacts.

Do not expose camera snapshot credentials/URLs directly.

## PTZ in live view

PTZ controls may overlay the focused live player when:

```text
camera.ptz permission
AND camera in scope
AND current capability says PTZ available
```

PTZ actions are sent through DeviceAdapter, not through browser access to camera endpoints.

Low-latency WebRTC is preferred when actively controlling PTZ.

## Live session reconnect

Frontend reconnect is bounded and stateful.

```text
transport interrupted
  ↓
short retry same MediaSession/runtime
  ↓
refresh session authorization if needed
  ↓
fallback transport/quality when policy allows
```

Camera/runtime generation change causes the old MediaSession to request/re-resolve current media rather than using stale URLs indefinitely.

## Media engine restart

If ZLMediaKit restarts:

- Camera domain state remains;
- RuntimeSupervisor rebuilds/adopts source streams;
- active MediaSessions receive reconnect/resolution signals;
- sessions re-resolve transport and current runtime generation;
- no Camera recreation occurs.

## Session limits

Protect resources with limits such as:

```text
max_live_sessions_per_user
max_live_sessions_per_camera
max_grid_sessions_per_user
max_turn_sessions
max_transcode_sessions
```

Limits may differ for Administrator/Operator/Viewer policy but authorization roles do not bypass hard server safety limits by default.

## Idle lifecycle

Browser heartbeat/visibility drives cleanup hints.

Sessions expire when:

- explicit close;
- authentication/session revoked;
- camera scope/permission revoked;
- heartbeat timeout;
- absolute session TTL reached;
- camera disabled;
- server safety policy terminates the session.

Idle ZLM source runtime may remain alive according to RuntimeSupervisor/recording/event needs; closing the last browser does not imply camera source disconnect if recording still needs it.

## User preferences

Per-user live-view preferences may persist:

```text
default_grid_layout
default_quality
audio_muted
auto_main_on_focus
show_stats
preferred_transport          auto | webrtc | fmp4 | hls
```

`preferred_transport` is a preference, not a guarantee; resolver may override when unsupported.

## Live layouts

First production release supports:

```text
1
2x2
3x3
4x4
custom saved layouts
fullscreen
popout/picture-like dedicated view where browser supports
```

A saved layout references Camera IDs and presentation settings, not permanent media URLs.

## LiveViewLayout

Conceptual model:

```text
LiveViewLayout
  id
  owner_user_id
  name
  is_default
  grid_definition
  created_at
  updated_at
```

Shared layouts may be added through explicit sharing/role policy; private per-user layout is the default.

## UI behavior

Live Monitor includes:

- layout selector;
- camera drag/drop;
- offline/error placeholder;
- preview/main quality badge;
- transport badge in diagnostics;
- mute/audio toggle;
- snapshot;
- PTZ when authorized;
- talk when authorized/supported;
- fullscreen;
- per-tile reconnect/status;
- optional live stats;
- saved layouts.

Normal users should not need to know source profile tokens or ZLM URLs.

## Health

System health exposes:

```text
ZLM health
WebRTC signaling health
STUN/TURN health
TURN allocations/bandwidth
fMP4/HLS availability
active live sessions
active transcodes
transcode capacity
session setup failures
first-frame latency
```

Per-camera live health remains distinct from recording/source health where possible.

## Audit and privacy

Do not write one AuditEvent for every ordinary view/heartbeat/frame.

Audit at minimum:

```text
live.snapshot_exported when persisted/downloaded under export policy
camera.talk_started
camera.talk_ended
live.admin_session_terminated where applicable
live.settings_changed for privileged global live settings
```

Ordinary live session diagnostics belong in operational/session telemetry.

Privacy rules:

- source credentials never reach browser;
- permanent bearer media URLs are forbidden;
- TURN secrets remain server-side;
- microphone capture starts only after explicit user action/permission;
- talk indicator is visible while microphone uplink is active.

## Acceptance tests

1. grid opens cameras on `live_preview` rather than pulling all main streams;
2. focusing a tile promotes to verified `live_main` and demotion returns to preview without rapid thrash;
3. WebRTC is preferred when supported and bounded failure falls back to fMP4/HLS;
4. H.265 recording continues natively while an incompatible browser receives H.264 live fallback/transcode;
5. no browser receives RTSP/ONVIF/vendor credentials;
6. revoked camera scope terminates/rejects future media access;
7. ZLM restart reconnects active UI sessions without recreating Camera domain rows;
8. multiple viewers share the same compatible transcode derivative rather than spawning one transcoder each;
9. transcode capacity exhaustion degrades live quality/fails clearly without affecting recording;
10. TURN credentials are short lived and relay/direct state is observable;
11. Grid audio is muted by default and focused audio can be enabled independently;
12. two-way talk requires `camera.talk`, is single-talker by default, and talk failure does not stop video;
13. PTZ overlay appears only with permission and current capability;
14. unsupported source audio falls back to video-only instead of failing live view;
15. offscreen/idle tiles release MediaSessions after policy grace while recording streams remain alive when needed.

## Invariants

1. MediaSession is short-lived authorization/runtime state; permanent media URLs are not domain truth.
2. Camera credentials and ZLM administration secrets never reach normal browsers.
3. Recording source selection is independent from browser live compatibility.
4. Grid uses preview-oriented streams by default; focused/fullscreen view may promote to main.
5. Browser/transport codec capability is probed rather than inferred only from user agent.
6. WebRTC is preferred for low latency, with bounded fMP4/HLS fallback.
7. H.265 recording is never downgraded globally merely because one browser cannot play H.265.
8. Transcoding is compatibility/on-demand infrastructure, not the default ingest path.
9. Compatible viewers share transcode derivatives where practical.
10. Recording/resource safety has priority over live-transcode demand.
11. TURN credentials are short-lived and scoped to authenticated live sessions.
12. Audio/talk failure is isolated from video and recording.
13. Talk is separately authorized and single-talker by default.
14. MediaSession/runtime-generation changes are recoverable without Camera recreation.
15. Live stats/heartbeats are operational telemetry, not high-volume AuditEvents.
16. Non-obvious transport fallback, codec negotiation, transcode sharing, TURN, and talk-concurrency behavior requires comments per Development Guidelines.