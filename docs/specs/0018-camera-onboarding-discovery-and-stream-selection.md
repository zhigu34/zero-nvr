# Spec 0018 — Camera Onboarding, Discovery, Capability Probe, and Stream Selection

Status: **accepted**

## Goal

Define the complete first-production-release camera/device onboarding model.

Core rule:

> Discovery finds candidates. Probe learns capabilities. Onboarding creates canonical Device/Camera/MediaStream objects only after identity, credentials, and media have been validated.

Protocol/vendor adapters remain replaceable. zero-nvr owns canonical device identity, camera/channel identity, stream-role selection, verification state, and user configuration.

## Device is not Camera

Do not assume one network endpoint equals one camera.

A physical/network device may expose multiple video sources/channels:

```text
IP camera
  Device 1
    └─ Camera 1

NVR / DVR
  Device 1
    ├─ Camera channel 1
    ├─ Camera channel 2
    └─ Camera channel N

multi-sensor camera
  Device 1
    ├─ sensor/channel A
    └─ sensor/channel B
```

Therefore introduce canonical Device separately from Camera.

## Device

Conceptual model:

```text
Device
  id
  display_name
  adapter
  manufacturer
  model
  firmware_version
  serial_number nullable
  hardware_id nullable
  stable_device_uid nullable
  enabled
  onboarding_state
  last_probe_at
  last_seen_at
  created_at
  updated_at
```

Device represents a managed external endpoint/appliance. Camera represents a logical video source/channel owned by or associated with a Device.

Manual RTSP sources that expose no reliable device-management identity may use a synthetic Device so the rest of the domain remains uniform.

## DeviceEndpoint

Network location is mutable and must not be the primary identity.

```text
DeviceEndpoint
  id
  device_id
  scheme
  host
  port
  path nullable
  adapter
  priority
  status
  last_verified_at
  created_at
  updated_at
```

A DHCP address change updates DeviceEndpoint rather than creating a new Camera when stable identity proves it is the same device.

## DeviceCredential

Business rows store only a SecretStore reference:

```text
DeviceCredential
  device_id
  credential_kind
  secret_ref
  verification_status
  verified_at
  updated_at
```

Credentials may be shared by several channels/profile endpoints belonging to one Device.

Normal APIs never return the stored password/token.

## DiscoveryCandidate

Discovery must not immediately create production Camera rows.

```text
DiscoveryCandidate
  id
  discovery_session_id
  adapter_hint
  endpoint
  device_uid_hint
  manufacturer_hint
  model_hint
  channel_count_hint
  matched_device_id nullable
  match_confidence
  state
  first_seen_at
  last_seen_at
  metadata
```

Candidates are temporary/read-model data and may expire.

## DiscoverySession

```text
DiscoverySession
  id
  requested_by
  adapters
  interfaces
  target_ranges
  state
  started_at
  completed_at
  candidate_count
  error_summary
```

Discovery is bounded, cancellable, and observable.

## Discovery methods

First production release supports:

```text
ONVIF WS-Discovery on selected local interfaces
manual ONVIF hostname/IP onboarding
manual RTSP onboarding
manual RTSP URI onboarding
HIK/vendor discovery/probe through adapter where supported
GB28181 device/channel inventory through WVP integration
```

Multicast discovery may not cross VLANs/subnets. The UI must explain this and provide explicit subnet/manual alternatives rather than reporting that no cameras exist.

Do not continuously scan arbitrary networks in the background by default.

## Discovery security

Discovery/probe is an administrative operation.

Rules:

- require camera.manage;
- restrict protocols/schemes to registered DeviceAdapters;
- validate host/port/range input;
- bound concurrency/timeouts;
- prevent unsupported URL schemes such as file://;
- do not expose a generic server-side fetch/proxy primitive;
- sanitize adapter errors before logs/UI;
- never log discovered/stored credentials.

## Stable identity and deduplication

Identity matching prefers protocol/vendor stable identifiers over address.

Possible evidence, in descending usefulness where trustworthy:

```text
protocol endpoint/device UUID
vendor device ID
serial number + manufacturer/model
hardware/MAC identity when reliably exposed
existing adapter-specific channel identity
endpoint/address only as weak fallback
```

Do not merge devices automatically on a weak address-only match when doing so could destroy an existing configuration.

Candidate matching outcomes:

```text
same_device
probable_match_requires_confirmation
new_device
identity_conflict
```

Identity conflicts are surfaced to the user and audited.

## Probe pipeline

Before final onboarding, zero-nvr runs a staged probe:

```text
endpoint reachability
   ↓
authentication
   ↓
device information
   ↓
channel/video-source enumeration
   ↓
media profile enumeration
   ↓
stream URI resolution
   ↓
actual media pull/probe
   ↓
capability probe
   ↓
clock/time probe where supported
```

A protocol control-plane success is not enough. At least one selected media stream must actually be pullable before the camera is marked verified.

## ProbeResult

```text
ProbeResult
  id
  discovery_candidate_id nullable
  device_id nullable
  adapter
  state
  started_at
  completed_at
  authentication_status
  control_status
  media_status
  capability_status
  clock_status
  sanitized_error
  raw_adapter_diagnostics_ref nullable
```

Raw diagnostics must never include plaintext credentials.

## DeviceCapabilitySnapshot

Normalized capability snapshot:

```text
DeviceCapabilitySnapshot
  device_id
  probed_at
  supports_events
  event_types
  supports_ptz
  ptz_features
  supports_snapshot
  supports_audio
  supports_two_way_audio
  supports_time_read
  supports_time_write
  supports_ntp_config
  supports_profile_management
  supports_reboot
  vendor_capabilities
  adapter_version
```

Capabilities are cached but may be re-probed.

Vendor-specific extensions stay namespaced in vendor_capabilities and must not redefine canonical capability fields.

## Camera / channel identity

Camera belongs to a Device and represents one logical video source/channel.

Recommended additions:

```text
Camera
  id
  device_id
  channel_key
  name
  enabled
  location
  manufacturer
  model
  form_factor
  storage_label
  created_at
  updated_at
```

`channel_key` is adapter-stable within the device where possible.

Examples:

```text
ONVIF video source token / stable channel mapping
HIK channel number
GB28181 channel/device code
manual RTSP synthetic channel key
```

Changing stream profiles must not create a new Camera identity.

## SourceMediaProfile

Persist discovered source profiles separately from selected MediaStream roles.

```text
SourceMediaProfile
  id
  device_id
  camera_id
  adapter_profile_key
  video_source_key
  name
  codec
  width
  height
  fps
  bitrate_kbps nullable
  bitrate_mode nullable
  gop_seconds nullable
  audio_codec nullable
  has_audio
  stream_uri_ref
  status
  discovered_at
  last_verified_at
  metadata
```

`stream_uri_ref` is an internal opaque connection reference, not a credential-bearing URI returned to the browser.

## Canonical stream roles

Camera maps discovered source profiles into canonical roles:

```text
recording
live_main
live_preview
detection
audio
```

These are product roles, not vendor profile names.

A single SourceMediaProfile may satisfy multiple roles.

Example:

```text
4K H.265 profile
  -> recording
  -> live_main where client path supports it

640x360 H.264 profile
  -> live_preview
  -> detection
```

## MediaStream

Canonical model should carry source/profile selection explicitly:

```text
MediaStream
  id
  camera_id
  role
  source_media_profile_id
  codec
  width
  height
  fps
  media_plane_key
  status
  selection_mode       auto | manual
  selected_at
  last_verified_at
```

Do not store browser-facing permanent URLs as domain truth.

## Automatic profile selection

Automatic selection is deterministic and explainable.

### recording

Prefer the highest-quality stable profile that:

- is pullable;
- uses a codec/container path supported by the recording pipeline;
- fits configured recording constraints;
- has acceptable media continuity.

Do not simply choose the numerically largest resolution when the stream repeatedly fails.

### live_main

Prefer good visual quality while considering browser/media-plane compatibility and bandwidth.

Recording profile and live profile do not have to be identical.

### live_preview

Prefer a lower-bandwidth secondary/sub stream suitable for grids and mobile/remote preview.

### detection

Prefer the lowest-cost profile that still meets detector requirements. It may reuse live_preview.

### audio

Select audio from the profile/track chosen by policy and capability.

Automatic selection stores a reason/score summary for diagnostics.

## Selection constraints

Camera settings may constrain auto selection:

```text
max_recording_resolution
preferred_video_codec
max_recording_bitrate
max_preview_resolution
prefer_substream_for_grid
detection_min_resolution
audio_enabled
```

Defaults should normally mean `auto` rather than forcing users to understand vendor profile tokens.

## Manual profile override

Advanced UI allows selecting exact discovered profiles for each canonical role.

Manual override survives re-probe as long as the adapter profile identity still exists.

If a selected profile disappears after camera firmware/config changes:

```text
role status -> selection_invalid
attempt safe auto fallback only if policy allows
surface warning
never silently switch recording quality without recording the reason
```

Profile fallback/switch is logged as runtime/config history.

## Codec compatibility

Source codec support is evaluated separately for:

```text
ingest
recording/remux
browser live playback
detection
export
```

A camera may be recordable even when its source codec is not natively playable in every browser.

MediaPlane decides whether live view can pass through, remux, or requires an explicitly configured transcode path.

Do not force a camera to H.264 globally merely because one browser path cannot consume H.265.

## Media verification

Selected streams are verified using actual media evidence, not URI existence alone.

Probe should capture enough diagnostics to verify:

```text
connect success
codec
resolution
fps observed
audio presence
first-frame latency
timestamp continuity
short sample stability
```

Use ONVIF profile metadata first and ZLMediaKit actual-stream state for runtime verification. FFprobe is a fallback/recovery inspection tool; FastAPI does not decode frames as a media server.

## Credential update flow

Replacing device credentials follows Spec 0012:

```text
new encrypted secret
   ↓
probe control + selected streams
   ↓
success
   ↓
atomically switch DeviceCredential secret_ref
   ↓
reconnect runtimes
   ↓
retire old secret
```

A failed credential test preserves the last working credential by default.

## Device address change / rediscovery

When a known stable device appears at a new endpoint:

```text
DiscoveryCandidate
   ↓ stable identity match
existing Device
   ↓
verify with credentials
   ↓
add/update preferred DeviceEndpoint
   ↓
reconnect
```

Do not create duplicate cameras merely because DHCP changed the IP.

If both old and new endpoints respond for the same stable identity, mark identity conflict and require resolution.

## Device replacement

Replacing a physical camera at the same mounting location is not automatically the same Camera identity.

UI supports an explicit replacement workflow:

```text
old Device/Camera
  -> retain historical identity/media
new Device/Camera
  -> optionally inherit display/location/recording policy
  -> new canonical device identity
```

This prevents historical footage from being falsely attributed to new hardware.

An advanced explicit `replace hardware, preserve logical Camera identity` operation may be supported only with clear audit/history semantics.

## Manual RTSP onboarding

Manual RTSP must be first-class, not a fallback hidden behind ONVIF.

Flow:

```text
name
host/RTSP URI
credentials
optional explicit secondary stream
   ↓
sanitize/store credential
   ↓
actual stream probe
   ↓
create synthetic Device + Camera
   ↓
create SourceMediaProfile(s)
   ↓
auto/manual role mapping
```

Credentials embedded in a supplied RTSP URI are extracted into SecretStore and removed from persisted/displayed URI material.

## ONVIF onboarding

ONVIF adapter handles:

- discovery;
- device information;
- video source/channel enumeration;
- media profiles;
- stream URI retrieval;
- event capability discovery;
- PTZ capability discovery;
- snapshot capability;
- clock/NTP capability;
- managed-time operations from Spec 0009.

zero-nvr normalizes these outputs; it does not make raw ONVIF profile tokens the product model.

## HIK onboarding

HIK devices may first use ONVIF when sufficient.

Vendor bridge is used for capabilities/events/control not adequately exposed through the standard adapter.

Do not create duplicate Device/Camera rows simply because both ONVIF and HIK adapters can see the same hardware.

Adapter binding may be:

```text
primary management adapter
+ supplemental vendor capability adapter
```

Identity correlation between adapters is explicit.

## GB28181 onboarding

WVP/device inventory is an integration source, not business authority.

GB28181 adapter normalizes platform/device/channel identity into Device + Camera + SourceMediaProfile.

WVP restart/re-registration must not recreate Camera IDs.

## Batch onboarding

First production release supports multi-select onboarding from discovered candidates.

Batch flow supports:

- shared/default credentials with per-device override;
- naming template;
- CameraGroup assignment;
- default RecordingPolicy;
- default StoragePool;
- default time-sync mode;
- auto stream-profile selection;
- per-device validation result.

The first production release also supports operator-supplied CSV batch import
for mixed ONVIF and manual RTSP rows. The CSV is parsed and previewed in the
browser rather than uploaded as an opaque server-side file.

The canonical CSV device fields are:

```text
type,name,host,onvif_port,rtsp_port,username,password,
main_path,sub_path,main_url,sub_url,location,storage_label,remark
```

ONVIF rows reuse `host`, `username`, and `password`, with
`onvif_port` defaulting to 80. RTSP rows reuse those same device fields,
with `rtsp_port` defaulting to 554. Normal RTSP rows provide
`main_path` / `sub_path`; zero-nvr URL-encodes credentials and builds the
RTSP URLs from the shared host/port. `main_url` / `sub_url` are advanced
full-URL overrides for devices whose stream syntax cannot be represented by
the normal path fields. The final `remark` column is ignored by import and is
reserved for operator guidance/notes. The downloaded template includes one
ONVIF and one RTSP example row; their `remark` cells explicitly tell the
operator to replace the sample data or delete those rows before importing.

Every valid row is then executed through the existing canonical single-device
onboarding path: ONVIF rows retain identity inspection/deduplication and
automatic usable-profile selection; RTSP rows retain the temporary ZLM media
probe before creation. Credentials are never echoed in the preview/result UI,
and the batch runner is sequential/bounded so a large file does not become an
unbounded LAN probe.

One failed device does not roll back unrelated successful devices.

## Onboarding transaction semantics

Each device/camera onboarding is staged.

```text
candidate
  ↓
probed
  ↓
prepared canonical objects
  ↓
commit configuration
  ↓
start runtime
  ↓
post-commit runtime verification
```

Failure before commit creates no half-configured production Camera.

Failure after commit leaves an explicit `needs_attention`/runtime-error state rather than deleting the Camera silently.

Batch onboarding records per-device results.

## Runtime capability refresh

Capability/profile probe runs:

```text
on onboarding
on explicit Refresh
after credential/endpoint change
after detected firmware/profile change
periodically at a low cadence if enabled
```

Do not aggressively poll device-management APIs.

Capability changes produce diffs and warnings where they invalidate configured behavior.

## Camera health layers

Keep separate:

```text
management/control health
media source health
event subscription health
clock health
PTZ capability/control health
```

A failed ONVIF management call does not necessarily mean an RTSP stream is offline, and a healthy control endpoint does not prove media is healthy.

## Deletion / disable semantics

`enabled=false` disables runtime activity but retains Camera identity/history.

Deleting a Camera with historical recordings/events is a high-risk archival operation and must follow Spec 0011 safety/audit semantics.

Device removal cannot silently orphan child Camera history.

## UI

Device Center first-release flows:

```text
[Discover Cameras]
[Add Manually]
[Import / Batch Add]

Discovery
  interface/subnet
  found candidates
  existing/new/conflict badges
  select candidates
  credentials
  Probe

Review Device
  identity
  firmware
  channels
  capabilities
  clock status

Streams
  Recording      Auto -> 4K profile
  Live main      Auto -> 1080p profile
  Preview/Grid   Auto -> sub stream
  Detection      Auto -> sub stream
  Audio          enabled/disabled

Test
  control ✓
  main stream ✓
  preview ✓
  events ✓/unsupported
  PTZ ✓/unsupported

[Add]
```

Advanced users can inspect exact adapter/profile tokens and probe diagnostics, but defaults stay understandable.

## Permissions and audit

camera.manage is required for discovery, onboarding, endpoint/credential/profile changes, capability refresh, and device replacement.

camera.ptz remains separate from camera.manage for operational PTZ control.

Audit at minimum:

```text
device.discovery_started
device.onboarded
device.endpoint_changed
device.credentials_updated
device.capabilities_refreshed
camera.created
camera.profile_selection_changed
camera.enabled
camera.disabled
camera.hardware_replaced
```

Secrets and credential-bearing URIs are redacted.

## Acceptance tests

1. ONVIF discovery finds candidates without creating Camera rows;
2. onboarding rejects bad credentials without overwriting the last working secret;
3. successful ONVIF onboarding enumerates channels/profiles and verifies selected media by actual pull;
4. a multi-channel NVR creates one Device with multiple Camera channels rather than duplicate physical devices;
5. DHCP IP change rediscovery matches stable device identity and updates endpoint without recreating Camera IDs;
6. weak/ambiguous identity match requires confirmation rather than auto-merging;
7. manual RTSP extracts embedded credentials into SecretStore and never returns them in APIs/logs;
8. automatic role selection chooses recording/preview/detection profiles and exposes the reason;
9. manual profile override survives re-probe while the source profile still exists;
10. removed source profile creates an explicit invalid-selection/fallback warning;
11. HIK supplemental adapter does not duplicate an ONVIF-discovered physical device;
12. GB28181/WVP re-registration preserves canonical Camera identity;
13. one failed item in batch onboarding does not undo unrelated successful items;
14. management-health failure and media-health failure are represented independently;
15. disabling a Camera keeps its historical recordings/events queryable.

## Invariants

1. Device and Camera are separate concepts; one Device may own many Camera channels.
2. Discovery candidates are never authoritative production Cameras.
3. Network address is mutable location, not primary device identity.
4. Stable identity evidence is preferred for deduplication; weak matches never silently merge.
5. Credentials live in SecretStore and are not duplicated into public connection/profile models.
6. Successful control-plane authentication alone is insufficient; selected media must actually be verified.
7. SourceMediaProfile and product MediaStream roles are separate.
8. Automatic profile selection is deterministic, explainable, and overrideable.
9. Recording/live/preview/detection roles may use different source profiles.
10. Browser codec limitations do not redefine the recording source profile globally.
11. Endpoint/profile/capability changes preserve canonical Camera identity when the underlying source is the same.
12. Physical hardware replacement is explicit and auditable.
13. ONVIF/HIK/GB28181/manual RTSP normalize into the same canonical Device/Camera/MediaStream model.
14. Capability/control/media/event/clock health are separate signals.
15. Onboarding failures never create silently half-configured production cameras.
16. Non-obvious identity matching/profile selection/vendor normalization behavior requires comments per Development Guidelines.

## Runtime lifecycle reference

Onboarding commits durable Device/Camera/SourceMediaProfile configuration. Long-term enable/disable/reconnect, configuration revision fencing, endpoint/credential/profile hot reconfiguration, event-subscription recovery, capability drift, and multi-channel disappearance/return behavior are defined in [Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift](0019-device-runtime-lifecycle-and-reconfiguration.md).

Discovery/onboarding state must not be reused as a permanent media runtime state machine. zero-nvr does not implement a generic LAN port scanner or default-password guessing workflow.


## Live playback role reference

The `live_preview` and `live_main` roles discovered/selected here are consumed by the MediaSession/LivePlaybackResolver defined in [Spec 0020](0020-live-view-media-session.md).

Browser compatibility does not redefine the recording profile. If an H.264-compatible live source profile is unavailable, Spec 0020 may create a temporary/shared compatibility transcode derivative for live viewing.
