# Spec 0006 — Historical Playback Timeline and Multi-Camera Sync

Status: **accepted**

## Goal

Define the playback model for:

- continuous playback across 5-minute RecordingSegments;
- gaps caused by no recording, source loss, purge, corruption, or remote-only media;
- event Marker rendering and aggregation;
- local/remote media resolution;
- single-camera seeking;
- multi-camera synchronized historical playback;
- buffering behavior that prioritizes user experience while preserving an optional strict forensic mode.

Core rule:

> Historical playback is driven by an absolute timeline. Physical MP4 boundaries are implementation details.

## User-experience principles

1. Dragging the timeline always selects an absolute time, not a file.
2. Crossing a 5-minute file boundary should feel like continuing the same recording.
3. A playback gap should explain why footage is unavailable when that reason is known.
4. Event markers must remain useful at both 24-hour and second-level zoom.
5. Multi-camera playback defaults to resilient synchronization: one slow camera must not unnecessarily freeze every other camera.
6. A strict synchronization mode is available when exact multi-camera temporal comparison matters more than uninterrupted playback.
7. Local, cached-remote, and remote-only footage share one logical timeline.
8. The UI never derives recording truth from filenames.

## Canonical time units

SQLite and PostgreSQL persist the same canonical UTC instants through the shared persistence model.

Playback API contracts use timezone-aware ISO 8601 timestamps:

```text
start_at
end_at
at
global_at
```

The frontend converts those instants into epoch milliseconds internally for Canvas layout, binary search, Master Clock math, and browser synchronization.

HTML video `currentTime` remains seconds because that is the browser API. Conversion is explicit inside the player/timeline layer rather than leaking millisecond integers into the public API.

Do not mix Unix seconds, naive datetimes, and video-relative seconds inside one public API/model.

## PlaybackTimeline response

The backend exposes a timeline-oriented view rather than raw filesystem objects.

Conceptual response:

```json
{
  "camera_id": "cam_01",
  "range": {
    "start_at": "2026-09-20T00:00:00Z",
    "end_at": "2026-09-21T00:00:00Z"
  },
  "segments": [
    {
      "id": "seg_01",
      "start_at": "2026-09-20T00:00:00Z",
      "end_at": "2026-09-20T00:05:00Z",
      "availability": "local",
      "playback_ref": "seg_01"
    }
  ],
  "gaps": [
    {
      "start_at": "2026-09-20T00:05:00Z",
      "end_at": "2026-09-20T00:10:00Z",
      "reason": "source_lost"
    }
  ],
  "events": [
    {
      "id": "evt_01",
      "type": "motion",
      "lifecycle_kind": "stateful",
      "start_at": "2026-09-20T00:01:40Z",
      "end_at": "2026-09-20T00:02:05Z"
    }
  ]
}
```

The frontend does not need local paths, S3/rclone/OpenList object keys, storage backend names, or human-readable recording filenames.


### Segment ordering and lookup

Detailed timeline responses return playable segments ordered by `start_at` ascending.

The frontend/player maintains this ordered list and uses binary search (or an equivalent indexed lookup) for absolute-time seek:

```text
target T
   ↓
binary search ordered segments
   ↓
find start_at <= T < end_at
   ↓
resolve playback_ref
   ↓
seek relative media offset
```

Do not linearly scan a full-day segment array for every playhead/synchronization tick.

For large ranges, the server may return compact coverage buckets rather than every physical segment; binary segment lookup applies to detailed playback ranges.

## Segment availability

Initial states:

```text
local
remote
cached_remote
missing
corrupted
purged
```

Meaning:

- local: playable from local storage;
- remote: valid media exists only on remote storage;
- cached_remote: remote media is already materialized/cached locally;
- missing: metadata expects media but no valid object is currently available;
- corrupted: media exists but failed integrity/playability checks;
- purged: media was intentionally removed by retention/disk policy.

Purged and unexpectedly missing media are different user-visible conditions.

Timeline coverage keeps availability explicit even when media is not playable.
A range backed by segment metadata may therefore appear in
`recording_ranges` as `missing`, `corrupted`, or `purged` while the same
interval also carries a user-facing gap reason. `cached_remote` is emitted only
when an AVAILABLE remote archive location still exists and a size-valid local
playback-cache file is present. A stale cache file never turns deleted/purged
canonical media back into `cached_remote`. Timeline inspection does not refresh
the cache file's TTL; only real playback/cache use does that.

## Gap model

An empty timeline range is not automatically "camera disconnected".

Initial gap reasons:

```text
not_scheduled
no_event
source_lost
runtime_restart
storage_failure
missing_media
purged
unknown
```

Examples:

- disabled policy or an interval outside an enabled recording schedule -> not_scheduled;
- event-only mode without a matching active RecordingTrigger -> no_event;
- RTSP/camera loss -> source_lost;
- ZLMediaKit server-start/restart evidence inside an otherwise empty interval -> runtime_restart;
- critical/unavailable health evidence for the camera's selected local recording StorageTarget -> storage_failure;
- object unexpectedly absent -> missing_media;
- retention removed media -> purged;
- no reliable explanatory evidence -> unknown.

Gap reasons are projections from persisted policy, segment/location truth, and
meaningful System Events. They are not guessed from nominal five-minute file
cadence. ZLM `server-started` persists an instantaneous per-camera
`runtime_health/runtime_restart` System Event for enabled recording policies;
storage failures reuse the existing bounded `storage_health` transition Event.
Schedule transitions are included as timeline boundaries so one returned gap
does not straddle scheduled and unscheduled wall-clock periods under one label.

The UI renders these as distinct states/tooltips instead of one generic black area.

## Timeline visualization

Use Canvas for high-density timeline rendering, zooming, panning, coverage, gaps, and markers.

DOM may still be used for tooltips, menus, accessible controls, event popovers, and labels outside the high-frequency drawing surface.

Suggested draw order:

```text
gap/background state
recording availability
event ranges / markers
selection / lock / annotations
ticks and labels
playhead
interaction overlay
```

Exact colors remain a UI/theme decision.


### Visual seam smoothing

Adjacent RecordingSegments may have tiny timestamp differences caused by timestamp rounding, container metadata, or capture jitter.

At wide zoom, if the real gap projects to less than approximately one display pixel, the renderer may visually join the adjacent recording blocks to avoid flickering hairline seams.

Conceptually:

```text
real gap exists in timeline data
        ↓
gap width < ~1 px at current zoom
        ↓
draw as visually continuous coverage
```

This is **rendering only**.

The backend/database gap must never be deleted, rounded away, or rewritten merely because it is too small to see at the current zoom. If the user zooms in far enough, the real gap becomes visible again.

Any fixed tolerance such as 500ms is an implementation tuning ceiling, not a rule that converts missing media into continuous media.

## Time-to-pixel model

For a viewport:

```text
view_start_at
view_end_at
canvas_width_px
```

calculate:

```text
ms_per_px =
    (view_end_at - view_start_at) / canvas_width_px

x =
    (time_ms - view_start_at) / ms_per_px
```

All tracks share this mapping.

## Zoom and navigation

Support at least:

- day overview;
- hour range;
- minute-level inspection;
- second-level event inspection.

User actions include click, drag, trackpad/wheel zoom, horizontal pan, previous/next recording, previous/next event, and jump to a selected time.

Zoom should stay centered around the cursor/playhead where practical.

## Event markers

Event remains the source of truth.

Instant event:

```text
time_ms
```

Render as a point/icon/vertical marker.

Stateful event:

```text
start_at
end_at
```

Render as a duration band/range.

## Event aggregation

At wide zoom, hundreds of events must not become hundreds of overlapping marks.

Conceptual behavior:

```text
24h view:
  14:00 bucket → 38 events

medium zoom:
  motion 12
  person 3
  vehicle 2

close zoom:
  individual events/ranges
```

Aggregation is only a query/render optimization. Canonical Events remain independent.

## PlaybackResolver

Timeline media references are stable logical IDs:

```text
playback_ref = RecordingSegment.id
```

Resolution:

```text
PlaybackResolver(segment_id)
    ↓
choose AVAILABLE RecordingLocation
    ├─ local/host-mounted -> ZLM VOD
    └─ remote archive -> rclone restore to bounded playback cache -> ZLM VOD
    ↓
short-lived authorized playback descriptor
```

Timeline responses do not permanently embed storage-specific URLs. Playback URLs/tokens may expire independently.

## Single-camera seek

When the user selects absolute time T:

1. find a playable segment satisfying start_at <= T < end_at;
2. resolve that segment;
3. calculate offset;
4. seek/play;
5. if no playable segment exists, show its gap/unavailable state.

```text
offset_seconds = (T - segment_start_at) / 1000
```

Clicking a known gap keeps the playhead at T; it must not silently snap elsewhere.

An optional "skip gaps" mode may jump during playback, but explicit seeking remains absolute.

## Continuous cross-segment playback

Initial V2 may use dual-player ping-pong:

```text
Player A = current segment
Player B = preload next segment

near boundary:
  resolve/preload B

boundary:
  switch active player

old A becomes next preload slot
```

Requirements:

- preload/resolve the next segment before the logical boundary;
- keep mute/volume/rate state consistent across both players;
- set the standby player to the expected starting offset and wait until it is actually ready enough to switch;
- switch according to the absolute segment boundary, not only an unreliable browser `duration` value;
- immediately recycle the old active player as the preload slot for the following segment;
- do not expose a physical file/player transition as a new logical recording item;
- emit diagnostics if the seam visibly stalls.

Segment selection/seek should use the ordered-segment binary lookup described above.

The product must not promise mathematically perfect gapless playback from independent MP4 files.

The timeline contracts must permit later replacement by MSE, fragmented MP4, virtual playlists, or server-side playback assembly without rewriting the domain model.

## Master playback clock

Single- and multi-camera synchronized playback use one absolute Master Clock.

Do not derive global time from whichever video currentTime event fired last.

Runtime clock:

```text
anchor_media_time_ms
anchor_monotonic_ms
playback_rate
state = playing | paused | seeking
```

While playing:

```text
global_time_ms =
    anchor_media_time_ms
    +
    (performance.now() - anchor_monotonic_ms)
      * playback_rate
```

Use a monotonic browser timer so operating-system wall-clock corrections cannot jump playback.

Refresh the visual playhead with requestAnimationFrame.

## Player synchronization

For each camera:

```text
channel_time_ms =
    current_segment_start_at
    + video.currentTime * 1000

drift_ms =
    channel_time_ms - global_time_ms
```

Initial behavior:

```text
|drift| < 250ms
  → no correction

250ms .. 1000ms
  → gentle playback-rate correction where safe

> 1000ms
  → hard seek to global time
```

These thresholds are tuning values, not domain constants.


The initial values may be adjusted after real-browser 4/9-camera tests. The desired behavior is stable:

- small drift: leave decoder alone;
- moderate drift: converge smoothly with a bounded temporary playback-rate adjustment;
- large drift: hard align by absolute seek.

Do not continuously oscillate playbackRate around the threshold; correction should use hysteresis/cooldown to avoid audible/visual hunting.

Explicit seek, source replacement, segment change, or large gap may require immediate hard correction.

## Multi-camera synchronized playback

All selected cameras share global_time_ms.

At the same T each camera independently resolves:

```text
playable segment
OR
gap/unavailable state
```

Example:

```text
Camera A: plays 14:05:00
Camera B: no recording at 14:05:00
Camera C: remote-only, loading
Camera D: plays 14:05:00
```

The shared playhead remains 14:05:00 for all channels.

A missing camera never shifts another camera to a different time.

## Synchronization modes

### tolerant — default

Optimized for normal review.

When one camera buffers:

- Master Clock continues;
- healthy cameras continue;
- buffering camera shows loading;
- when ready it seeks to current global time and rejoins.

This prevents one slow/remote channel from freezing a 4/9-camera review.

### strict

Optimized for forensic comparison.

When a participating camera that should be playing buffers significantly:

- pause Master Clock;
- pause healthy playable channels;
- recover/prebuffer delayed channel;
- align all participating playable channels;
- resume together.

A camera with a legitimate gap at `global_time_ms` does not participate in the strict buffering barrier and does not block other cameras.

Only a camera that is expected to have playable media at the current absolute time can acquire the strict-mode barrier.

The user may switch modes.

## Playback speed

Initial review speeds:

```text
0.5x
1x
2x
4x
8x
```

Higher speeds may be added later.

At elevated rates:

- audio may be muted above a product-defined threshold;
- sync correction accounts for selected rate;
- preload distance increases;
- event timing remains absolute.

## Gap skipping

Optional:

```text
skip_gaps = off | on
```

When enabled:

- if every selected camera is in a non-playable gap, jump to the earliest next playable time;
- in multi-camera playback, do not skip time merely because one camera has a gap while another has media.

## Remote-only playback

Remote media stays on the same timeline:

```text
remote RecordingLocation AVAILABLE
   ↓
PlaybackResolver
   ↓
rclone restore/copyto
   ↓
bounded local playback cache
   ↓
ZLM VOD
   ↓
player
```

UI states include remote available, restoring, cached/ready, playing, and remote error. The V1 baseline does not require FUSE/rclone mount.

Remote loading never changes global timeline time by itself.

## API range and detail

Timeline queries are range-based:

```text
camera_ids
from=<ISO8601>
to=<ISO8601>
detail=day|hour|minute
```

The V1 single-camera endpoint accepts the same explicit detail contract:

```text
GET /cameras/{camera_id}/timeline?from=...&to=...&detail=day|hour|minute
```

The response echoes the accepted `detail` value so frontend cache/render state
cannot confuse a day overview with a minute inspection. Omitting `detail`
defaults to `minute` for backward compatibility with the original detailed
timeline behavior. The current day/hour/minute contract does not round or erase
authoritative recording/gap boundaries. Later event aggregation and detailed
physical-segment payloads build on this contract without changing the range
semantics.

The initial frontend mapping is:

- 24-hour view -> `day`;
- 6-hour view -> `hour`;
- 1-hour view -> `minute`.

Large ranges may return compact coverage/aggregation. Close zoom may return
detailed events/segments as the later aggregation and segment-detail roadmap
items are implemented.

The frontend must not download a year of second-level markers merely to draw a daily overview.

## Multi-camera query model

The API may return multiple tracks aligned to one requested range:

```json
{
  "range": { "start_at": 1, "end_at": 2 },
  "tracks": [
    {
      "camera_id": "cam_01",
      "segments": [],
      "gaps": [],
      "events": []
    },
    {
      "camera_id": "cam_02",
      "segments": [],
      "gaps": [],
      "events": []
    }
  ]
}
```

## Timeline UI behavior

Recommended UI:

- one shared horizontal time ruler;
- one track per selected camera;
- one shared vertical playhead;
- camera player grid;
- event filters;
- visible tolerant/strict sync control for multi-camera mode;
- gap/event/recording tooltips;
- clear local/remote/missing/purged states;
- zoom and quick date/time navigation.

Single-camera playback is the same model with one track.

## Recovery and discontinuity

Use actual:

```text
started_at
ended_at
availability
completion_reason
```

Do not assume all segments are exactly five minutes.

If recovery creates slight overlap, select one authoritative ordered playback interval and avoid double-playing it.

If a true hole exists, show the gap. Never stretch/invent timestamps to hide missing media.

## Diagnostics

Useful runtime diagnostics:

```text
camera_id
global_time_ms
segment_id
segment_start_at
segment_end_at
availability
resolved_backend
buffering_state
drift_ms
last_seek_reason
last_source_switch_reason
sync_mode
```

These may be runtime/debug data rather than permanently persisted rows.


## Playback acceptance tests

Implementation validation must include at least:

1. **absolute seek**
   - seek into the first/middle/last second of a segment;
   - verify the resolved media time maps back to the requested absolute time within expected container/keyframe tolerance;

2. **cross-segment continuation**
   - play across many consecutive 5-minute boundaries;
   - verify no logical timeline reset;
   - measure visible seam/stall and log source-switch diagnostics;

3. **visual gap scaling**
   - inject small and large real gaps;
   - verify tiny gaps may visually disappear at day zoom but reappear when zoomed in;
   - verify source gap data remains unchanged;

4. **event alignment**
   - place point and stateful events at/between segment boundaries;
   - verify Marker positions remain aligned through zoom/pan;

5. **tolerant multi-camera sync**
   - throttle one channel;
   - verify healthy channels continue;
   - verify recovered channel rejoins current Master Clock;

6. **strict multi-camera sync**
   - throttle one playable channel;
   - verify participating playable channels pause/re-align/resume;
   - verify a camera with a legitimate gap does not hold the barrier;

7. **remote-only media**
   - mix local and remote-only segments in one range;
   - verify the timeline stays fixed while remote media resolves/caches;

8. **storage migration**
   - move a RecordingSegment from local to verified remote-only;
   - verify PlaybackTimeline identity/time remains unchanged because playback_ref is stable.

## Initial V1 implementation choices

- Canvas timeline;
- timezone-aware ISO 8601 Playback API; frontend converts to milliseconds internally;
- PlaybackResolver by RecordingSegment ID;
- dual HTML video ping-pong initially;
- Master Clock from monotonic browser time;
- tolerant multi-camera sync by default;
- optional strict sync;
- event aggregation by zoom;
- explicit gap reasons;
- local and remote-only segments on one timeline.

The implementation must preserve contracts that allow later upgrade to MSE/fMP4/virtual playlists without rewriting the timeline/domain model.

## Invariants

1. Absolute time, not MP4 filename/order, controls playback.
2. Playback API timestamps use timezone-aware ISO 8601 timestamps consistently.
3. Playback references are stable and storage URLs are resolved lazily.
4. A 5-minute file boundary does not create a new logical playback session.
5. Known no-media reasons are explicit gaps rather than all being labeled disconnected.
6. Event is the Marker source of truth.
7. Wide timeline views aggregate events; close views expose individual markers.
8. Multi-camera playback uses one Master Clock.
9. Default tolerant sync lets healthy cameras continue when another buffers.
10. Strict sync pauses/re-aligns participating playable channels when necessary.
11. A legitimate gap in one camera never changes another camera's global time.
12. Local, cached-remote, and remote-only media share the same logical timeline.
13. Purged and unexpectedly missing media are distinct states.
14. Playback may upgrade beyond dual HTML video without changing timeline/domain contracts.
15. Real timestamp holes are shown, never hidden by invented continuity.
16. Detailed segment ranges are ordered and absolute-time seek uses indexed/binary lookup rather than repeated full linear scans.
17. Sub-pixel seam smoothing is a visualization optimization only and never erases a real timestamp gap from authoritative data.
18. Strict-mode buffering barriers include only channels expected to have playable media at the current absolute time.
19. Non-obvious playback timing/synchronization/buffering logic requires comments per Development Guidelines.

## Source-loss gap origin

Historical `source_lost` gaps are derived from real RecordingSegment coverage plus source/runtime connectivity evidence. A reconnect creates a new physical RecordingSegment rather than stretching timestamps across the outage. Source-connectivity recovery rules are defined in [Spec 0008 — Stream Loss, Reconnect, and Recording Recovery](0008-stream-reconnect-and-recording-recovery.md).

## Canonical clock reference

Historical playback and the multi-camera Master Clock remain aligned to canonical UTC RecordingSegment time. Camera clock skew affects device-originated event normalization/OSD agreement, not the playback clock itself. See [Spec 0009 — Canonical Time, Camera Clock Offset, and Timezone Handling](0009-time-and-camera-clock.md).

## Authorization reference

Timeline queries and PlaybackResolver media access require backend permission plus effective camera scope. Playback URLs/tokens are short-lived/scoped and losing camera scope must not leave permanent media access behind. See [Spec 0011 — Authentication, Camera-Scoped Authorization, and Audit](0011-auth-authorization-and-audit.md).
