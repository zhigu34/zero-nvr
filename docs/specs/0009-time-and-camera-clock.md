# Spec 0009 — Canonical Time, Camera Clock Offset, and Timezone Handling

Status: **accepted**

## Goal

Define one consistent time model for:

- recording metadata;
- human-readable recording filenames;
- camera on-screen display (OSD) alignment;
- ONVIF/vendor event timestamps;
- pre-roll/post-roll calculations;
- schedule recording;
- historical playback;
- multi-camera synchronization;
- device clock monitoring and optional NTP management.

Core rule:

> zero-nvr owns canonical time. Camera clocks are external clocks that are measured, monitored, and optionally synchronized.

## Three time layers

zero-nvr separates three concepts.

### 1. Canonical system time

Authoritative business/storage time:

```text
UTC
```

All persisted authoritative timestamps use UTC.

Examples:

```text
RecordingSession.started_at
RecordingSession.ended_at
RecordingSegment.started_at
RecordingSegment.ended_at
DetectionEvent.started_at
DetectionEvent.ended_at
SourceConnectivityIncident.started_at
SourceConnectivityIncident.ended_at
```

The server/NVR host clock is the canonical wall-clock source for zero-nvr.

The deployment should keep the host synchronized through a reliable NTP/time-sync service.

### 2. Camera/device clock

The camera has its own wall clock.

It may be:

- correct and NTP synchronized;
- manually configured;
- using a different timezone;
- several seconds/minutes wrong;
- drifting over time;
- corrected abruptly after a reboot/time-sync event.

zero-nvr never assumes the device clock equals canonical system time.

### 3. Presentation / recording timezone

Human-facing date/time is rendered with an IANA timezone.

Effective recording timezone:

```text
camera recording_timezone override
        |
        +-- if absent --> system recording_timezone
```

This timezone controls:

- recording directory date;
- human-readable recording filename start time;
- default timeline labels;
- schedule wall-clock interpretation where configured;
- camera-time management target timezone when zero-nvr manages compatible devices.

It does not change canonical UTC timestamps.

## Recording filenames

RecordingSegment canonical started_at remains UTC.

The visible filename:

```text
{name_id}_{YYYY-MM-DD}_{HH-MM-SS}.mp4
```

is produced by:

```text
RecordingSegment.started_at UTC
        |
convert to effective recording_timezone
        |
human-readable filename
```

Do not generate filenames from the camera's current clock.

This ensures the file index remains consistent even if a camera clock is wrong or later corrected.

If the camera OSD is expected to match the filename, the correct solution is to synchronize/monitor the camera clock, not to make zero-nvr adopt a bad camera clock.

## Device clock probing

For devices that expose a clock API, zero-nvr periodically samples device time.

ONVIF devices support GetSystemDateAndTime, which exposes:

- UTC device time;
- local device time;
- configured timezone;
- daylight-saving indication;
- whether time is manual or NTP managed.

The adapter normalizes available device-clock information into zero-nvr.

Conceptual sample:

```text
CameraClockSample
  camera_id
  sampled_at
  device_utc_at_sample
  device_local_at_sample
  device_timezone
  device_time_source
  round_trip_ms
  offset_ms
  uncertainty_ms
  quality
  metadata
```

## Offset measurement

A device-time request takes network time.

Do not calculate offset only from the response-receive timestamp.

For one sample:

```text
server_send_utc    = t0
device_utc         = td
server_receive_utc = t1

server_midpoint = t0 + (t1 - t0) / 2

offset_ms =
    device_utc - server_midpoint

uncertainty_ms ~= (t1 - t0) / 2
```

Meaning:

```text
offset_ms > 0
  camera clock is ahead of zero-nvr

offset_ms < 0
  camera clock is behind zero-nvr
```

Prefer several short samples and choose a stable/low-latency estimate (for example median/best-RTT filtering) rather than trusting one slow request.

Exact sampling/filtering parameters are implementation tuning.

## Camera clock status

Maintain current normalized clock status:

```text
CameraClockStatus
  camera_id
  offset_ms
  uncertainty_ms
  measured_at
  device_timezone
  device_time_source
  sync_mode
  health
```

Possible health states:

```text
unknown
healthy
warning
critical
unsupported
```

Clock-skew thresholds are configurable health thresholds, not timeline/business semantics.

A practical initial product may warn at a few seconds and escalate for large offsets, but exact defaults should be tuned through real-device testing.

## Device clock management modes

Per camera:

```text
time_sync_mode =
  monitor
  manage_ntp
  ignore
```

### monitor — default

zero-nvr:

- reads device time when supported;
- measures offset;
- shows clock health;
- does not modify camera configuration.

This is the safe default because changing a camera clock can also affect the camera's own SD-card recordings, logs, alarms, and external integrations.

### manage_ntp

When explicitly enabled and supported:

- configure/use the selected NTP server(s);
- configure the intended timezone/DST behavior;
- verify the resulting device UTC clock after configuration;
- continue monitoring drift.

ONVIF provides Get/SetSystemDateAndTime and NTP configuration operations for compatible devices.

The NTP source is configured explicitly in zero-nvr/system settings. Do not assume the zero-nvr host itself is an NTP server unless the deployment actually provides that service.

### System NTP settings for managed cameras

System Settings must expose a dedicated time section.

Conceptual configuration:

```text
SystemTimeSettings
  recording_timezone
  managed_camera_ntp_mode     manual | dhcp
  managed_camera_ntp_servers[]
  clock_warning_threshold_ms
  clock_critical_threshold_ms
```

Recommended UI:

```text
System Settings
└─ Time
   ├─ Recording timezone
   ├─ Managed camera NTP source
   │    ├─ DHCP
   │    └─ Manual
   ├─ NTP server 1
   ├─ NTP server 2
   ├─ NTP server 3
   └─ Clock health thresholds
```

Rules:

- `managed_camera_ntp_servers` configures the NTP source zero-nvr will attempt to apply to cameras whose `time_sync_mode = manage_ntp`;
- use hostname or IP according to device capability;
- allow multiple ordered servers at the zero-nvr configuration level even if some cameras support only one; each adapter applies the subset supported by that device;
- validate empty/invalid server entries before device changes;
- changing the system NTP list does not silently rewrite every camera immediately unless the user applies/synchronizes the change;
- camera-level override may be introduced for devices that must use a different NTP source.

Default inheritance:

```text
camera time_sync_mode = manage_ntp
        |
        +-- camera NTP override exists
        |      -> use camera override
        |
        +-- otherwise
               -> use SystemTimeSettings managed camera NTP settings
```

The system NTP setting is for managed cameras. It is **not** automatically the zero-nvr host operating-system NTP configuration.

In initial V2, zero-nvr monitors host clock synchronization/health but does not reconfigure chrony, systemd-timesyncd, ntpd, or equivalent host services. Host time-service management can be added later as an explicit operations feature.


### ignore

Do not probe/manage device clock. Use this for unsupported or intentionally isolated devices.

## One-click / UI time sync

For compatible managed devices, UI may offer:

```text
Clock offset: +12.4s
Device time source: Manual
Timezone: CST-8
Status: Warning

[Configure NTP / Sync device time]
```

A time-setting operation is an administrative device change and should:

- require appropriate permission;
- be audited;
- verify the result;
- surface vendor/ONVIF errors rather than silently assuming success.

## Event timestamp model

DetectionEvent should preserve both source and normalized timing.

Conceptual fields:

```text
source_occurred_at
received_at
occurred_at
timestamp_source
timestamp_quality
clock_offset_ms_applied
```

Canonical event lifecycle fields derive from occurred_at:

```text
started_at
ended_at
```

### Local/server-generated event

Examples:

- local RTSP motion detector;
- zero-nvr internal trigger;
- server-side AI using the received media timeline.

Use canonical server/media time directly.

```text
timestamp_source = server
clock_offset_ms_applied = 0
```

### Device-reported event with device timestamp

If the adapter knows that the timestamp comes from the camera clock and has a sufficiently reliable measured offset:

```text
occurred_at =
    source_occurred_at
    - device_clock_offset
```

Example:

```text
camera clock is +12s fast

camera says event: 14:10:12
offset: +12s

canonical event: 14:10:00
```

Persist the applied offset with the event.

### Device event without reliable timestamp/offset

If the source timestamp is absent, invalid, ambiguous, or clock quality is too poor:

```text
occurred_at = received_at
timestamp_quality = fallback_receive_time
```

Do not guess an exact camera occurrence time.

## No retroactive timestamp rewriting

Once an event/segment timestamp has been normalized and persisted, later clock measurements do not silently rewrite history.

Example:

```text
12:00 measured offset +12s
13:00 camera NTP fixes itself to +0.2s
```

Events normalized at 12:30 retain the recorded offset/quality that was known when they were ingested.

Otherwise historical markers would move after the user already reviewed/exported the footage.

Explicit repair/reindex tooling may be designed separately if required.

## Recording media timestamps

RecordingSegment absolute timestamps do **not** come from camera OSD text or camera wall-clock configuration.

They are anchored to zero-nvr/media-ingest canonical time and finalized using actual media duration/timestamp evidence.

Camera RTP/codec timestamps are used for media continuity/duration as appropriate, but they are not automatically treated as trustworthy UTC wall clock.

This prevents a camera that is 10 minutes wrong from placing files 10 minutes into the wrong historical timeline.

## Camera OSD

OSD timestamp is pixels burned into the video image. zero-nvr usually cannot reinterpret those pixels as the canonical timeline.

Desired behavior:

```text
canonical time
≈ camera OSD time
```

is achieved by device time synchronization/monitoring.

If the device clock is known to be wrong:

- zero-nvr timeline/files remain correct;
- UI shows clock-offset warning;
- exported video still contains the camera's own incorrect burned-in OSD until the device is corrected.

Do not shift the entire NVR timeline merely to make a wrong OSD look correct.

## Timezone and OSD alignment

To make filenames and OSD visually agree:

1. choose the camera/system recording_timezone;
2. configure the camera to the same local timezone when device management is enabled;
3. configure camera NTP to a reliable source;
4. verify camera UTC offset after synchronization.

The underlying canonical timeline remains UTC.

## Schedule timezone

Schedules are wall-clock business rules and must carry an explicit timezone.

Conceptually:

```text
RecordingPolicy.schedule_timezone
```

Default:

```text
camera effective recording_timezone
```

A schedule such as:

```text
08:00 - 18:00
```

means 08:00–18:00 in that timezone, including daylight-saving transitions.

Do not persist recurring schedules as fixed UTC hours if the user's intent is local wall-clock time.

## Daylight-saving transitions

Canonical UTC avoids ambiguous historical time.

Human-readable filename/time presentation may contain repeated local wall-clock values during a DST fall-back hour.

Normal filename format remains compact.

If two files would collide because the same local start second occurs twice, use the existing exceptional collision suffix:

```text
{name_id}_{YYYY-MM-DD}_{HH-MM-SS}_{segment_short_id}.mp4
```

Database UTC timestamps remain unambiguous.

## System wall-clock changes

Wall clock and elapsed-duration timers serve different purposes.

Use canonical UTC wall clock for:

- persisted timestamps;
- timeline positioning;
- schedule evaluation;
- filenames after timezone conversion.

Use a monotonic clock for in-process elapsed timers such as:

- pre-roll/post-roll countdown decisions after anchoring;
- retry delays/backoff;
- health timeout intervals;
- playback master clocks;
- debounce/hold timers.

An NTP correction of the host wall clock must not accidentally make a 10-second post-roll timer run for 2 seconds or 40 seconds.

## Host clock health

Because zero-nvr canonical time depends on the host clock, system health should expose time synchronization state where available.

Conceptual health data:

```text
host_time_sync_state
last_sync_at
estimated_offset_ms
source
```

If host time is materially unsynchronized:

- raise system health warning/critical state;
- continue recording where possible;
- mark timestamp quality/diagnostics so the problem is observable;
- do not silently switch authority to a random camera clock.

## Multi-camera playback alignment

Multi-camera historical playback aligns cameras by canonical UTC RecordingSegment time.

Camera clock offset is primarily relevant to:

- device-originated event timestamps;
- OSD visual agreement;
- device logs/alarms.

It does not directly modify Playback Master Clock.

### Media transport latency

Camera clock skew and media transport latency are different.

```text
device_clock_offset_ms
!=
media_transport_latency_ms
```

Do not subtract RTSP/network latency from a device event timestamp merely because a video frame arrived later.

Initial V2 uses canonical ingest/segment time for multi-camera playback.

If future forensic requirements demand tighter scene-capture alignment, zero-nvr may add a distinct optional media alignment calibration based on trustworthy RTP/RTCP/vendor timing.

That future media offset must be modeled separately from CameraClockStatus.

## Late events

A corrected canonical event timestamp may be older than received_at.

That is valid.

Example:

```text
event occurred canonically at 14:10:00
event received at          14:10:03
```

RecordingManager uses the authoritative occurred_at for Marker/pre-roll coverage calculations.

If required pre-roll media has already expired from the buffer, record observable pre-roll degradation rather than moving the event timestamp forward.

## UI behavior

Camera details should show clock information when supported:

```text
Device clock
  Source: NTP / Manual / Unknown
  Device timezone
  Offset from NVR
  Last checked
  Status
  Sync mode
```

Timeline/event detail may show timestamp quality in diagnostics, not necessarily in the normal end-user view.

System Settings should expose:

```text
recording_timezone
managed_camera_ntp_mode
managed_camera_ntp_servers[]
host clock-health status
clock warning thresholds
```

## Acceptance tests

1. camera clock +12s fast:
   - filename/timeline remains canonical;
   - device event timestamp is corrected by measured offset;
   - OSD warning is visible;

2. camera switched from manual time to NTP:
   - new clock samples converge;
   - historical event timestamps do not move;

3. camera timezone differs from recording_timezone:
   - warning/metadata reflects mismatch;
   - canonical UTC remains correct;

4. device timestamp missing:
   - event falls back to received_at with explicit quality;

5. late device event:
   - canonical event can predate received_at;
   - pre-roll coverage degradation is explicit when needed;

6. host NTP wall-clock correction:
   - monotonic post-roll/retry timers do not jump;

7. DST fall-back:
   - canonical UTC is unambiguous;
   - filename collision fallback prevents overwrite;

8. schedule across DST:
   - schedule keeps local wall-clock intent in schedule_timezone;

9. multi-camera playback:
   - Playback Master Clock remains canonical UTC;
   - device clock correction does not directly shift recorded segment timelines.

## Invariants

1. Canonical persisted business/media timestamps are UTC.
2. Server/NVR canonical time is authoritative; camera clocks are measured external clocks.
3. Human filenames/UI use configured timezone but never become timestamp authority.
4. Recording filenames derive from canonical RecordingSegment.started_at, not camera wall clock.
5. Device-originated timestamps retain source, receive time, correction offset, and quality.
6. Reliable camera-clock offset may normalize device event timestamps.
7. Historical normalized timestamps are not silently rewritten when clock offset later changes.
8. OSD mismatch is corrected by camera time sync/health, not by shifting the NVR timeline.
9. Schedule rules carry an explicit wall-clock timezone.
10. Elapsed timers use monotonic time after their canonical anchor is established.
11. Host clock health is observable because host UTC is canonical.
12. Device clock skew and media transport latency are separate concepts.
13. Multi-camera playback remains aligned on canonical UTC.
14. DST/local-time filename collisions use exceptional suffixing rather than overwriting media.
15. Managed-camera NTP servers are explicit system configuration and may be inherited/overridden per camera.
16. Initial V2 monitors host NTP/time-sync health but does not modify the host operating-system time-sync service.
17. Non-obvious clock correction/timezone/timer logic requires comments per Development Guidelines.
