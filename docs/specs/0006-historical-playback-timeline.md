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

The V1 single-camera timeline returns canonical physical segment ranges in
`segments`, ordered by `start_at`, then `end_at`, then stable segment ID.
These ranges keep their full canonical boundaries even when the requested
viewport clips through the middle of a segment. Each item exposes
`playback_ref = RecordingSegment.id` plus availability; storage paths and
object keys remain private. The merged `recording_ranges` array remains the
compact visual coverage layer.

The frontend/player maintains this ordered segment list and uses binary search
for absolute-time seek:

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

Do not linearly scan a full-day segment array for every playhead/synchronization
tick. The lookup finds the rightmost segment whose `start_at <= T`, verifies
`T < end_at`, derives `offset_ms = T - start_at`, and resolves that stable
segment ID. If no segment contains T, the client uses the absolute-time resolver
only to obtain the authoritative gap reason and neighboring-time metadata.

The current single-camera V1 viewport returns physical segments even when
`recording_ranges` and Event markers are aggregated for wider zoom levels.
Future very-large or multi-camera overview APIs may omit physical segments and
return compact coverage only, but detailed playback ranges must preserve this
ordered lookup contract.

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

The V1 single-camera implementation uses one `PlaybackTimelineCanvas` drawing
surface for the ruler, gaps, recording availability, protection ranges, event
markers, and the vertical playhead. Every layer uses the same absolute
time-to-pixel transform. DOM remains responsible for the legend, controls, and
tooltips.

Interaction keeps media truth separate from viewport navigation:

- click/keyboard seek selects an absolute time;
- pointer drag pans the viewport without changing the selected playback time;
- horizontal trackpad/wheel motion pans after a short debounce;
- vertical wheel zooms through the current 24h / 6h / 1h detail levels;
- wheel zoom preserves the cursor's absolute-time anchor where practical;
- toolbar zoom recenters around the current playback time;
- `currentAt` remains the single playhead input shared by playback and the
  Canvas renderer.

The later multi-camera synchronization roadmap items remain separate from this
renderer conversion.


### Visual seam smoothing

Adjacent RecordingSegments may have tiny timestamp differences caused by timestamp rounding, container metadata, or capture jitter.

At wide zoom, the V1 Canvas renderer visually joins a gap only when all of the
following are true:

- the gap reason is `unknown` rather than an explicit semantic outage;
- both immediate neighboring recording ranges are playable
  (`local`, `remote`, or `cached_remote`);
- the real gap duration is no more than 500 ms;
- the projected width is no more than one physical display pixel at the current
  device-pixel ratio.

Explicit `source_lost`, `storage_failure`, `missing_media`, `purged`,
`not_scheduled`, and `no_event` gaps are never visually hidden by this rule.

Conceptually:

```text
real gap exists in timeline data
        ↓
gap width < ~1 px at current zoom
        ↓
draw as visually continuous coverage
```

This is **rendering only**.

The renderer suppresses the gap hatch and paints a narrow bridge between the two
recording bars; it still keeps the original gap hit target/tool-tip and never
changes `timeline.gaps`, `recording_ranges`, RecordingSegment timestamps, or
playback seek behavior. When zoom makes the same gap wider than the pixel
threshold, the hatch becomes visible again automatically.

The backend/database gap must never be deleted, rounded away, or rewritten merely because it is too small to see at the current zoom. If the user zooms in far enough, the real gap becomes visible again.

The 500 ms tolerance is an implementation ceiling, not a rule that converts
missing media into continuous media.

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

V1 uses the timeline `detail` contract to select deterministic marker density:

```text
detail=day
  -> 1-hour aggregate buckets

detail=hour
  -> 5-minute aggregate buckets

detail=minute
  -> exact canonical Event markers
     - ended_at == started_at -> point
     - ended_at > started_at -> range
     - ended_at is null -> ongoing range
```

Aggregate markers include `count`, `category_counts`, and `label_counts`.
A stateful Event contributes to every aggregate bucket it actually overlaps, so
a long-running event remains visible throughout its duration instead of only in
the bucket containing its start time. Bucket IDs are synthetic response IDs;
they are never persisted and never replace canonical Event identity.

The Canvas renderer draws individual points as vertical markers, individual
stateful Events as duration bands, and aggregate buckets as count bands. Clicking
a point jumps to the exact Event time, clicking a range seeks to the clicked
absolute time inside that range, and clicking an aggregate bucket seeks near its
center for drill-in navigation.

Aggregation is only a query/render optimization. Canonical Events remain independent.

## PlaybackResolver

Timeline media references are stable logical IDs:

```text
playback_ref = RecordingSegment.id
```

Resolution:

```text
PlaybackResolver(segment_id, offset_ms)
    ↓
choose AVAILABLE RecordingLocation
    ├─ local/host-mounted -> ZLM VOD
    └─ remote archive -> rclone restore to bounded playback cache -> ZLM VOD
    ↓
short-lived authorized playback descriptor
```

Timeline responses do not permanently embed storage-specific URLs. Playback URLs/tokens may expire independently.

The stable public resolver is:

```text
POST /recordings/{segment_id}/playback/resolve
{
  "offset_ms": 0
}
```

`offset_ms` must fall inside the segment's canonical wall-clock duration.
Authorization is evaluated against the segment's Camera scope before storage
resolution. The older absolute-time convenience endpoint remains available:

```text
POST /cameras/{camera_id}/playback/resolve
{
  "at": "<timezone-aware ISO8601>"
}
```

It first selects the segment covering the requested absolute time, derives the
relative offset, and then uses the same media-location resolver. Both paths
therefore share local/remote/cache precedence, remote restore scheduling,
short-lived ZLM authorization, and missing/purged media semantics. A leftover
playback-cache file by itself is never sufficient to resurrect a segment whose
canonical RecordingLocations are no longer AVAILABLE.

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

The V1 single-camera player uses two reusable HTML video elements in a
ping-pong arrangement:

```text
Player A = active segment
Player B = resolved/preloaded next contiguous segment

active segment ends:
  swap A/B
  old active slot is cleared
  preload the following segment into the free slot
```

Preloading uses the ordered timeline segment list and the stable
RecordingSegment-ID resolver. A next segment is eligible only when its
canonical start is not after the current segment end, so the player never
silently crosses a real timeline gap. Remote-only next segments may start their
existing bounded-cache restore while the current segment is still playing.

The standby player is not considered switchable merely because its signed URL
was resolved. The browser must report at least `HAVE_FUTURE_DATA` for the
standby element. If the canonical boundary arrives first, the active player is
paused at that absolute instant and the logical playhead remains on the boundary
until the standby element becomes ready.

Source switching is driven by the active RecordingSegment's canonical
`end_at`. The implementation schedules a boundary check from media-relative
`currentTime`, re-checks the absolute media time when the timer fires, and also
checks on `timeupdate`; browser `ended` is only a fallback signal. It does
not use `video.duration` as recording truth.

When adjacent physical segments overlap slightly, the next segment is resolved
with the offset corresponding to the current segment's canonical `end_at`.
Segments fully covered by the current segment are skipped. A candidate whose
`start_at` is after the boundary is a real gap and is never crossed by the
ping-pong player.

This readiness/boundary layer still uses the active media element clock. The
later Master Clock and drift-correction roadmap items replace that timing source
without changing the segment or resolver contracts.

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

Do not derive global time from whichever video `currentTime` event fired last.

The V1 frontend implements a dedicated `MasterPlaybackClock` with:

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

`performance.now()` is the only advancing time source for the logical playback
clock, so operating-system wall-clock corrections cannot jump playback. The
clock is re-anchored only on explicit logical transitions such as seek,
play/pause, and canonical segment-boundary switching.

`PlaybackView` refreshes `currentAt` and the Canvas playhead with
`requestAnimationFrame`. Media `timeupdate` events no longer advance the
global time; they remain available for boundary fallback and the following
drift-correction item, where per-player media time is compared against this
Master Clock.

The clock already carries `playback_rate`, but the user-facing multi-speed
controls remain a separate roadmap item.

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
  -> no correction

250ms .. 1000ms
  -> bounded temporary playback-rate correction

>= 1000ms
  -> hard seek media to the Master Clock
```

The V1 single-player controller uses a 250 ms soft-entry threshold and a
150 ms soft-exit threshold, so playback-rate correction has hysteresis rather
than toggling at one boundary. Temporary rate correction is bounded to roughly
1.5%..4% around the Master Clock's logical playback rate and is re-evaluated no
more often than every 750 ms.

A hard seek has a 1000 ms threshold and a 1000 ms cooldown. Hard alignment
changes only the active media element's `currentTime`; it never rewinds or
advances the Master Clock to match a lagging decoder. Immediately after a hard
seek the media rate returns to the Master Clock's base rate while the cooldown
prevents repeated seeks from stale browser timing events.

The controller measures:

```text
media_time_ms =
    playback_anchor_ms
    + video.currentTime * 1000

drift_ms =
    media_time_ms - master_clock_time_ms
```

Positive drift means the media is ahead and is temporarily slowed; negative
drift means it is behind and is temporarily accelerated. Explicit seek,
source/segment replacement, pause/resume, and A/B player switching reset the
controller and restore the media element to the Master Clock's base rate.

These thresholds are tuning values, not domain constants. They may be adjusted
after real-browser 4/9-camera tests, while preserving the stable policy:

- small drift: leave decoder alone;
- moderate drift: converge smoothly with bounded rate correction;
- large drift: hard align media to absolute Master Clock time.

This item corrects the active single-camera player only. The following tolerant
and strict multi-camera items reuse the same per-player drift controller rather
than redefining clock behavior.

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

## Aligned multi-camera timeline query

Multi-camera review uses one bounded batch read model:

```text
POST /api/v1/playback/timeline

{
  "camera_ids": ["...", "..."],
  "from": "<timezone-aware ISO8601>",
  "to": "<timezone-aware ISO8601>",
  "detail": "day | hour | minute"
}
```

The request accepts 2–9 unique Camera IDs. The backend applies
`recording.view` plus effective Camera scope to **every** requested Camera
before producing any tracks. If any Camera is missing or out of scope, the
whole batch fails rather than returning a partial response that could reveal a
hidden Camera.

The response contains one shared `range` / `detail` plus ordered
`tracks[]`. Each track is the same existing `PlaybackTimeline` read model,
built by `PlaybackTimelineService.build()`; availability, gaps, physical
segments, and event aggregation therefore have one implementation for both
single- and multi-camera playback.

```text
{
  "detail": "hour",
  "range": { ... },
  "tracks": [
    { "camera_id": "A", ...PlaybackTimeline },
    { "camera_id": "B", ...PlaybackTimeline }
  ]
}
```

Track order follows request order. The browser keeps the aligned tracks by
Camera ID and feeds the focused Camera's track to the existing Canvas timeline.
Media resolution remains independent per Camera and still uses absolute-time /
RecordingSegment-ID resolvers; the batch timeline endpoint never returns media
URLs or creates a persistent multi-camera playback session.

## Synchronization modes

### tolerant — default

Optimized for normal review.

The V1 Playback view may select up to nine participating cameras. The focused
camera remains the owner of the detailed timeline, protect/export actions, and
date/zoom controls; additional cameras join a synchronized review grid.

All tiles receive the same absolute Master Clock time and playback state. Each
camera independently calls the existing camera playback resolver for that
absolute time and owns its own remote-restore retry, media buffering state, and
`PlaybackDriftController`.

When one camera buffers:

- Master Clock continues;
- healthy cameras continue;
- buffering camera shows loading;
- remote-only restore remains local to that tile;
- a legitimate gap remains a per-camera gap state;
- when the delayed tile becomes playable it aligns its media to the **current**
  Master Clock time and rejoins rather than rewinding the shared clock.

Secondary tiles are muted by default; the focused camera follows the shared mute
control. Explicit timeline seek/date navigation increments a synchronization
generation so every participating tile re-resolves the new absolute time
together.

The browser fetches the participating Cameras' timeline tracks in one aligned
batch request. The focused track remains authoritative for the visible Canvas,
while all tracks retain the same absolute range for synchronization and later
gap-skipping decisions. Media resolve remains per-Camera so a remote restore or
slow channel stays isolated to that tile.

This prevents one slow/remote channel from freezing a 4/9-camera review.

### strict

Optimized for forensic comparison and explicitly optional. Tolerant mode remains
the default.

Every participating tile publishes one synchronization state:

```text
resolving
ready
buffering
pending
gap
unavailable
```

The strict barrier treats `resolving`, `buffering`, `pending`, and
`unavailable` as blockers. `ready` does not block. A canonical `gap`
never blocks because there is no media that camera is expected to present at
that absolute time.

During a strict barrier:

- the user's play intent remains recorded even though actual playback is paused;
- Master Clock freezes at one absolute time;
- healthy playable tiles pause at that same time;
- pending remote media may continue restoring in the background;
- buffering/resolving tiles continue preparing media;
- when the last blocker reports ready or canonical gap, all playable tiles
  realign to the frozen Master Clock time before playback resumes together.

A newly selected absolute time first marks participating tiles unresolved, so
strict playback cannot race ahead using stale readiness from the previous seek.
Once a resolver classifies a camera as a legitimate gap, that camera is removed
from the barrier immediately.

Resolver/integration errors remain blockers in strict forensic review because
synchronized evidence cannot be guaranteed while the channel state is
unknown. The operator can remove that camera or switch back to tolerant mode;
switching to tolerant immediately releases the barrier and preserves the
user's prior play intent.

The Playback toolbar exposes `Tolerant / Strict` only while more than one
camera participates. Strict is UI/runtime synchronization state only; it adds
no persistence table and does not change RecordingSegment/Event truth.

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

Gap skipping is an optional runtime playback control and is off by default:

```text
skip_gaps = off | on
```

It never changes canonical time, RecordingSegment boundaries, `gaps`, or
Canvas rendering. It changes only where the playback controller seeks next.

A timeline range is considered playable only for
`local / remote / cached_remote` availability. `missing`, `corrupted`,
and `purged` ranges are not valid skip targets.

Single-camera behavior:

- when resolver playback lands in a gap while autoplay is requested, inspect the
  loaded timeline for the earliest later playable range;
- jump to that range's absolute `start_at` when one exists;
- a paused/manual gap view is left in place rather than unexpectedly moving the
  user's playhead.

Multi-camera behavior:

- use the aligned tracks for every current participant;
- if any selected Camera is playable at `global_time_ms`, do **not** skip;
- only when every selected Camera is non-playable, jump to the earliest future
  playable range across all tracks;
- the jump goes through the shared Master Clock path, so tolerant mode resumes
  immediately while strict mode re-enters its normal readiness barrier at the
  new absolute time.

The loaded timeline/aligned-track window is authoritative for an automatic
skip decision. If no later playable range is present in that read model, the
player does not guess from filenames or jump into an unverified catalog segment;
the user may pan/change range or use normal timeline navigation.

Gap skipping never compresses or rewrites the visible timeline: skipped periods
remain visible and can still be selected explicitly with the control disabled.

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
