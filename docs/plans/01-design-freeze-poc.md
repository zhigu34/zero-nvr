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
