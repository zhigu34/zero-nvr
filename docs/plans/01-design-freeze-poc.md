# V1 Design-Freeze POC Plan

Status: **required before architecture freeze**

These POCs validate the few remaining media/storage assumptions that must not be guessed in production design.

## POC-01 — ZLM continuous recording and indexing

Validate:

- camera RTSP -> ZLM ingest;
- ZLM MP4 recorder;
- target segment duration around 300s;
- actual start/end/duration metadata;
- on_record_mp4 hook;
- index insertion;
- API/DB restart while ZLM continues an already-running recording where practical;
- reconciliation after a deliberately lost hook.

Pass condition: RecordingSegment catalog can be reconstructed without ffprobe in the normal path and without media loss caused by control-plane restart.

## POC-02 — fMP4 abnormal termination

Candidate configuration:

```ini
[record]
enableFmp4=1
```

Test process kill, ZLM restart, and host/container abrupt-stop simulations.

Validate that the current file remains usable/recoverable and that:

- ZLM VOD can consume it;
- FFmpeg/ffprobe can inspect/remux it;
- browser playback path remains usable;
- archive/restore does not alter validity.

Pass condition: fMP4 demonstrates materially better crash resilience without breaking normal playback/export.

## POC-03 — EVENT_ONLY pre-roll

Target product behavior:

- default pre-roll ~10s;
- default post-roll ~10s;
- event UPDATE/new event can extend end time;
- no duplicate recorder is started;
- independent events remain independent markers.

Evaluate mature ZLM-native mechanisms first:

- rolling HLS/fMP4 segments;
- recorder/GOP cache behavior;
- other existing ZLM capabilities.

Do not implement a custom compressed-video packet ring buffer.

Pass condition: stable pre-roll coverage is demonstrated across real cameras/codecs/GOP intervals with explicit degradation when coverage is unavailable.

## POC-04 — multi-event extension

Example:

```text
event A -> planned end 20:00:20
event B at 20:00:17 -> extend planned end to 20:00:27
```

Validate that media recording remains one logical active interval while Event A and Event B remain separately queryable and visible on the timeline.

## POC-05 — timeline precision

Validate actual file times rather than assuming fixed 300-second segments.

Cases:

- normal rollover;
- source loss/reconnect;
- partial final segment;
- restart;
- DST/UI timezone conversion;
- camera clock offset.

Pass condition: wall-clock timeline, gap projection, and event markers remain correct.

## POC-06 — ZLM VOD seek

Validate:

- seek to media offset;
- wall-clock -> RecordingSegment -> media offset mapping;
- speed playback where used;
- codec/browser compatibility paths;
- gap boundary behavior.

## POC-07 — remote restore playback

Path:

```text
rclone-supported remote
-> worker restore/copyto
-> bounded local playback cache
-> ZLM VOD
-> browser
```

Validate:

- first-play latency;
- prefetch next segment;
- cache eviction;
- interrupted download/retry;
- remote failure does not affect local recording;
- OpenList WebDAV path behaves like another rclone remote.

## POC-08 — stream sharing / camera connection count

For a main+sub camera, validate that ZLM is the camera-facing media bus.

Expected shape:

```text
camera main -> ZLM
camera sub  -> ZLM

Live / Recorder / Frigate consume ZLM internal streams
```

Pass condition: downstream consumers do not each create duplicate camera RTSP connections in Managed mode.

## POC-09 — SQLite load

Validate both:

- 8-camera baseline;
- 16-camera extended target.

Workload:

- recording segment indexing;
- Event inserts/updates;
- Timeline queries;
- retention decisions;
- audit writes;
- concurrent API reads.

Pass condition: SQLite remains a first-class production mode with acceptable latency and no need for Redis/another mandatory service.

## POC-10 — recovery reconciliation

Deliberately simulate:

- lost recording hook;
- API restart;
- worker restart;
- DB temporary unavailability;
- stale catalog entry;
- missing file.

Pass condition: zero-nvr converges to explainable state without silently deleting valid recording media.

## Freeze rule

When all critical media-path POCs pass, change project status from:

```text
V1 Design Freeze Candidate
```

to:

```text
V1 Architecture Frozen
```

After that, changes to component ownership, recording authority, core container boundaries, or storage lifecycle require an ADR.


## Execution rules

These POCs are architecture gates, not throwaway demos.

For every POC, commit or preserve:

- exact ZLMediaKit/FFmpeg/rclone/SQLite versions;
- relevant configuration;
- test camera/source description without secrets;
- test steps/commands;
- raw timestamps and expected/actual result;
- representative logs;
- generated metadata/sample file references where practical;
- pass/fail conclusion;
- any architecture change required by the result.

Do not mark a POC passed only because one happy-path demo worked once.

## Minimum test matrix

Where the capability applies, include at least:

- one H.264 camera/source;
- one H.265 camera/source when available;
- main + sub stream camera behavior;
- normal source;
- deliberate source interruption/recovery;
- zero-nvr API restart;
- ZLM restart;
- SQLite default mode.

For EVENT_ONLY/pre-roll tests, include at least two different GOP/keyframe intervals when test sources allow it.

## Quantitative / objective pass criteria

### POC-01 — Continuous recording and indexing

Pass only if:

- at least three consecutive normal recording segments finalize and index correctly;
- catalog start/end/duration uses actual media metadata rather than assuming exactly 300 seconds;
- restarting FastAPI does not deliberately stop an already-running ZLM recorder;
- one intentionally dropped hook is recovered by reconciliation;
- reconciliation is idempotent and creates no duplicate RecordingSegment row for the same physical media;
- ffprobe is not required in the normal successful hook path.

### POC-02 — fMP4 abnormal termination

Pass only if abnormal termination tests show that the in-progress recording has materially better recoverability than ordinary MP4 for the tested ZLM configuration and:

- ffprobe can inspect the surviving file;
- ZLM VOD can open the surviving valid coverage;
- FFmpeg can remux/export the surviving valid coverage;
- finalized normal recordings remain browser-playable through the intended playback path;
- no new mandatory repair daemon/process is required.

If fMP4 causes unacceptable VOD/browser/export regressions, do not make it the default even if crash recovery is better.

### POC-03 — EVENT_ONLY pre-roll

For configured pre-roll `P` and the chosen ZLM-native buffer fragment/granularity `G`:

```text
expected usable coverage >= P - G
```

unless the source itself makes this impossible.

Pass only if:

- no custom H.264/H.265 packet ring buffer is required;
- repeated triggers obtain stable pre-event coverage within the documented ZLM mechanism/granularity;
- H.264 and H.265/GOP differences are documented;
- unavailable coverage is reported as degraded rather than fabricated;
- memory/disk use of the rolling mechanism is bounded and calculable per camera.

If no mature ZLM-native mechanism can meet the product target reliably, the architecture decision must be revisited before freeze.

### POC-04 — Multi-event extension

Pass only if:

- two overlapping Events remain two independent Event/RecordingTrigger records;
- only one normal ZLM recorder is active;
- the effective stop deadline extends to the latest required post-roll;
- a third update near the deadline can extend it again without recorder restart;
- removal/completion of one trigger never stops recording while another reason remains active.

### POC-05 — Timeline precision

Pass only if:

- a normal segment rollover has no artificial gap/overlap in the projected wall-clock timeline;
- an intentional source outage produces a gap matching actual missing media time within the available media timestamp granularity;
- a partial final segment is represented by its real duration;
- UTC persistence and configured timezone display round-trip correctly;
- DST boundary tests do not rewrite canonical timestamps;
- Event markers map to the correct wall-clock recording position.

### POC-06 — ZLM VOD seek

Pass only if:

- resolving a wall-clock timestamp inside a segment seeks to the expected media neighborhood;
- repeated seeks across at least three positions in a segment are stable;
- seeking near the beginning/end of a segment behaves correctly;
- a gap timestamp returns an explicit no-media result with previous/next playable boundaries;
- the selected browser/player path can resume from the resolved position.

Document practical seek tolerance imposed by keyframe/container behavior rather than pretending sample-exact seeking is guaranteed.

### POC-07 — Remote restore playback

Pass only if:

- a remote-only segment is restored through rclone into bounded local playback cache;
- partial/interrupted restore retries safely without publishing a corrupt READY cache entry;
- ZLM can play the restored file;
- next-segment prefetch works without blocking local recording;
- cache eviction never deletes canonical local RecordingLocations;
- OpenList WebDAV behaves through the same rclone abstraction when tested;
- no FUSE mount is required for the baseline path.

Record first-play latency for representative local-LAN remote and Internet/cloud remote tests when available. It is an operational metric, not a single universal release threshold.

### POC-08 — Stream sharing / connection count

Pass only if a main + sub camera produces the expected camera-facing connections:

```text
main -> ZLM
sub  -> ZLM
```

and Live/Recorder/Frigate consume ZLM-managed/internal streams rather than independently creating additional camera RTSP pulls in Managed mode.

Verify with camera session count, network capture, camera admin UI, or equivalent evidence.

### POC-09 — SQLite load

Test both 8-camera baseline and 16-camera extended target.

Pass baseline only if:

- no database-lock error storm occurs under representative recording/event/API workload;
- recording hook/catalog writes remain reliable;
- Timeline/Event queries remain interactively usable;
- WAL/checkpoint behavior remains bounded;
- backup can complete without corrupting or freezing the workload;
- no Redis/PostgreSQL dependency is required merely to make the 8-camera target work.

For 16 cameras, record actual latency/throughput and classify the result:

```text
PASS
PASS WITH DOCUMENTED HARDWARE/CONFIG REQUIREMENT
or
POSTGRESQL RECOMMENDED ABOVE THIS LOAD
```

Do not demote SQLite from first-class status based on assumption; use measured evidence.

### POC-10 — Recovery reconciliation

Pass only if the system converges correctly after each deliberate fault:

- missed recording hook;
- API restart;
- worker restart;
- temporary database unavailability;
- stale catalog row;
- missing local file;
- extra valid media file not referenced by the current database.

Required properties:

- valid media is never auto-deleted merely because metadata is stale;
- reconciliation is idempotent;
- duplicate catalog rows/locations are not created;
- missing media becomes explainable state;
- recovered media becomes playable when identity can be proven;
- ambiguous objects remain diagnosable instead of being guessed into place.

## Freeze evidence

Before changing project status to `V1 Architecture Frozen`, create a short result document for each POC, for example:

```text
docs/poc-results/
  01-zlm-recording.md
  02-fmp4-crash.md
  03-event-preroll.md
  ...
  10-reconciliation.md
```

Each result document must state:

```text
Result: PASS | FAIL | PASS WITH CONSTRAINTS
Tested versions:
Test environment:
Evidence:
Known limitations:
Architecture impact:
```

`PASS WITH CONSTRAINTS` is acceptable only when the constraint is explicit in product/deployment documentation and does not violate PROJECT_BASELINE.

Any failed POC that changes component ownership, recording authority, Core container boundary, storage lifecycle, or database-default policy requires an ADR before the architecture can be frozen.
