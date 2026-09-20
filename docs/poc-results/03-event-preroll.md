# POC-03 — EVENT_ONLY Pre-roll

Result: **PASS**

## Primary candidate

~~~text
one ZLM normal recorder
-> short finalized fragments in bounded shared tmpfs
-> on_record_mp4
-> Event/RecordingTrigger overlap selects whole fragments
-> copy/verify/atomic publish
-> persistent RecordingSegment + RecordingLocation
~~~

Events change the **promotion window**, not recorder state.

## Harness

~~~text
poc/zlm-recording/scripts/run-event-preroll.sh
~~~

The harness has been executed successfully on the final fMP4 design-freeze baseline.

## Test matrix

The automated matrix uses:

- H.264 with ~2 second GOP;
- H.264 with ~5 second GOP;
- H.265/HEVC with ~2 second GOP.

The H.265 run is not trusted by source naming alone: every promoted fragment is inspected with ffprobe and the group passes only when the actual video codec is `hevc`.

Each stream uses the same configured:

- ~10 second pre-roll;
- ~10 second post-roll;
- short ZLM fragment target;
- bounded shared tmpfs.

The test generates ten Event trigger timestamps distributed across many fragment boundaries.

## Required checks

For every Event at T:

~~~text
earliest promoted coverage <= T - pre_roll
latest promoted coverage   >= T + post_roll
~~~

within the explicitly documented timestamp tolerance of the tested ZLM hook metadata.

Also require:

- one ZLM normal MP4 recorder stays active before/during/after Events;
- normal ZLM on_record_mp4 hooks drive finalized fragment discovery;
- ephemeral tmpfs fragments are not inserted into the canonical POC recording catalog merely because they exist;
- whole overlapping fragments are promoted without synchronous trimming/transcode;
- a fragment needed by multiple Events is promoted only once;
- promotion uses *.partial -> verify -> atomic rename;
- tmpfs capacity is actually bounded and peak bytes are recorded;
- old unneeded ephemeral files are GC'd;
- while an Event/RecordingTrigger window is active, FastAPI can be stopped and restarted without stopping the ZLM rolling recorder;
- after restart, a fresh process can reconstruct required coverage from the persisted SQLite RecordingTrigger fact + finalized tmpfs filesystem scan **without** depending on a PrebufferFragment table or successful hook history;
- selected recovery fragments are copied through *.partial -> verify -> atomic publish;
- the recovery evidence separately reports which promoted fragments had no successful hook row, but hook rows are not used for selection;
- actual fragment duration distribution is recorded for both GOP intervals.

## H.265

The committed harness includes a synthetic H.265 source using libx265.

If the selected MediaMTX/FFmpeg test image cannot provide libx265 on the execution host, that is an explicit test-environment limitation; POC-03 cannot be marked unconditional PASS without an equivalent HEVC run.

## Comparison candidates

The result must also document comparison findings for:

- ZLM startRecordTask(back_ms, forward_ms);
- ordinary startRecord with a pre-created ZLM frame GOP Ring.

Current source audit already shows reasons these are not the primary candidate, but runtime comparison evidence is still useful.

## Expected evidence

~~~text
poc/zlm-recording/runtime/event-preroll-gop2.json
poc/zlm-recording/runtime/event-preroll-gop5.json
poc/zlm-recording/runtime/event-preroll-h265.json
poc/zlm-recording/runtime/event-preroll-recovery-state.json   # diagnostic snapshot only; SQLite trigger is authoritative for recovery
poc/zlm-recording/runtime/event-preroll-recovery.json
poc/zlm-recording/runtime/event-docker-compose.log
poc/zlm-recording/runtime/pre-roll-candidate-comparison.json
poc/zlm-recording/runtime/event-recordings/
~~~

## Tested versions

Final fMP4 regression baseline:

~~~text
GitHub Actions run: 35490737812
job: POC 03
head SHA: 20ae4741b480269bb61b69a8b4b123a46163af02
ZLMediaKit:
  branch: master
  commit: b794772
  buildTime: 2026-09-20T02:21:00
managed recording mode: fMP4
MediaMTX image: bluenviron/mediamtx:1.21.0-ffmpeg
~~~

## Test environment

GitHub-hosted Ubuntu 24.04.5 / x86_64 Docker runner.

Configured prebuffer:

~~~text
segment target = 5 s
pre-roll = 10 s
post-roll = 10 s
buffer window = 35 s
tmpfs hard size = 268,435,456 B
~~~

## Evidence

Three codec/GOP matrices each executed ten Event trigger times.

~~~text
H.264 / ~2 s GOP
  trigger coverage: 10 / 10 PASS
  actual codec: h264
  fragment duration: 3.960 .. 5.961 s
  tmpfs peak: 7,596,732 B
  promoted fragments: 20
  GC removed: 16
  rolling recorder active after Events: true

H.264 / ~5 s GOP
  trigger coverage: 10 / 10 PASS
  actual codec: h264
  fragment duration: 4.959 .. 9.961 s
  tmpfs peak: 3,610,887 B
  promoted fragments: 12
  GC removed: 11
  rolling recorder active after Events: true

H.265 / ~2 s GOP
  trigger coverage: 10 / 10 PASS
  actual codec: hevc
  fragment duration: 3.932 .. 5.935 s
  tmpfs peak: 3,264,939 B
  promoted fragments: 20
  GC removed: 16
  rolling recorder active after Events: true
~~~

All groups kept tmpfs far below the 256 MiB hard bound.

### FastAPI restart / no PrebufferFragment table

A durable RecordingTrigger requested:

~~~text
required start = 2026-09-20T04:51:19.874717Z
required end   = 2026-09-20T04:51:39.874717Z
~~~

FastAPI was stopped for 14 seconds while ZLM continued rolling the tmpfs recorder.

After restart:

~~~text
recorder active = true
filesystem finalized fragments scanned = 6
selected/promoted fragments = 4
published coverage =
  2026-09-20T04:51:17Z
  ..
  2026-09-20T04:51:41Z
~~~

The recovery process selected/promoted media from the persisted RecordingTrigger + direct tmpfs/media scan. Hook history was read only afterward for evidence, not for selection.

### Comparison mechanisms

`startRecordTask(back_ms=10000, forward_ms=1000)` was called five times:

~~~text
durations:
  9.201
  9.878
  10.558
  9.241
  9.921 s

distinct first-frame hashes = 5
~~~

Every call returned a different output file/task. This confirms it is useful as a fixed clip primitive but is not a natural “extend one unknown-duration EVENT_ONLY recorder” API.

Ordinary `startRecord` after priming the frame GOP Ring showed:

~~~text
live time between start/stop ≈ 5.003 s
recorded duration ≈ 13.159 s
historical media recovered ≈ 8.156 s
raw Hook start vs estimated media start bias ≈ 7.570 s
~~~

So GOP-ring startRecord can recover history, but its raw Hook absolute timing is unsuitable as the V1 canonical Event-recording timeline without extra timing logic.

Primary artifact:

~~~text
GitHub Actions artifact:
  poc-03-evidence
  run 35490737812
  artifact id 10599227297
  digest sha256:1e1d29e4ad1ad1df1624ef777e6cbeab7fa13cb12ce03e5f6af576fb9c6ee671
~~~

## Known limitations

- Frequent Events whose required windows are separated by less than approximately one fragment can cause whole-fragment retention to bridge the gaps, approaching continuous retained coverage. This is expected and safe; it trades extra disk for a simpler hot path.
- The 256 MiB tmpfs is a POC cap, not a production default. Production sizing must be derived from stream bitrate, buffer duration, and enabled EVENT_ONLY camera count.
- POC-05 timing findings apply to canonical RecordingSegment timestamp normalization; the EVENT_ONLY test proves required media coverage/promotion, while the accepted continuity-session resolver establishes canonical timestamps.
- The final regression matrix ran with the accepted fMP4 default from ADR 0009.

## Architecture impact

**Accepted V1 EVENT_ONLY baseline:**

~~~text
Camera
  -> ZLMediaKit
  -> one continuously-running short-fragment recorder
  -> bounded tmpfs
  -> on_record_mp4 / filesystem reconciliation
  -> Event/RecordingTrigger required window
  -> promote whole overlapping finalized fragments
  -> verify + atomic publish
  -> RecordingSegment + RecordingLocation
~~~

Events change promotion/retention state, not recorder state.

V1 therefore does **not** need:

- a custom compressed-packet ring;
- a second camera pull;
- duplicate event recorders;
- a persistent PrebufferFragment table;
- a persistent RecordingSession table;
- synchronous FFmpeg trim/concat in the recording hot path.
