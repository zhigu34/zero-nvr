# V1 Design-Freeze POC Plan

Status: **required before architecture freeze**

These POCs validate the few remaining media/storage assumptions that must not be guessed in production design.

## Gate classification

Not every experiment has the same release meaning.

### A — Core architecture freeze gates

These validate assumptions that the default complete V1 architecture depends on:

~~~text
POC-01  normal ZLM recording / hook indexing / control-plane independence
POC-03  EVENT_ONLY pre-roll
POC-04  overlapping Event extension
POC-05  canonical wall-clock timeline precision
POC-06  ZLM VOD seek / PlaybackResolver primitive
POC-07  remote restore playback baseline
POC-08  Core ZLM stream sharing / source connection count
POC-09  SQLite default production mode
POC-10  reconciliation / eventual-consistency safety
~~~

Architecture freeze requires each of these to be PASS or PASS WITH CONSTRAINTS whose constraint is already reflected in the baseline and does not contradict the product target.

### B — implementation-selection gate

POC-02 decides the **default recording container strategy**, not whether ZLMediaKit remains the recording owner.

~~~text
POC-02 PASS
  -> fMP4 may become the default after its normal playback/export path is accepted

POC-02 FAIL / no material advantage
  -> keep ordinary MP4 as the V1 default
  -> document abnormal-termination limitation
  -> architecture ownership remains unchanged
~~~

Therefore POC-02 does not by itself block V1 Architecture Frozen when ordinary MP4 remains an acceptable, explicitly documented fallback. It must still be resolved before declaring the default container-format decision complete.

### C — optional-feature integration gates

Optional services do not become Core architecture prerequisites.

Examples:

- Managed Frigate must prove `AI_DETECT -> ZLM internal stream` and unchanged source-camera session count before Managed AI is declared production-ready.
- OpenList support must smoke-test a real OpenList WebDAV endpoint through the already accepted rclone abstraction before OpenList integration is declared production-ready.
- coturn must be validated only for deployments enabling remote TURN/WebRTC traversal.
- managed PostgreSQL/Mosquitto profiles are validated when those optional deployment modes are implemented.

A user who leaves one of these features disabled must not need to pull or run its service merely to satisfy the Core architecture.


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

Run the same abrupt SIGKILL/restart scenario first with ordinary MP4 and then with `record.enableFmp4=1`.

Validate candidate fMP4 recovery and compare it against the ordinary-MP4 baseline under the same source/write interval. The current file should remain usable/recoverable and:

- ZLM VOD can consume it;
- FFmpeg/ffprobe can inspect/remux it;
- browser playback path remains usable;
- archive/restore does not alter validity.

Pass condition: fMP4 passes the required recovery/playback/export checks **and** the ordinary-MP4 baseline fails at least one equivalent interrupted-file recovery check. If both are equally recoverable on the tested ZLM/filesystem, the POC does not prove a material fMP4 advantage.

## POC-03 — EVENT_ONLY pre-roll

Target product behavior:

- default pre-roll ~10s;
- default post-roll ~10s;
- event UPDATE/new event can extend end time;
- no duplicate recorder is started;
- independent events remain independent markers.

Evaluate the current mature ZLM-native candidates in this order:

1. **rolling normal ZLM MP4/fMP4 recorder into bounded tmpfs + whole-fragment promotion**;
2. ordinary startRecord with a pre-created ZLM frame GOP Ring;
3. startRecordTask(back_ms, forward_ms) as a fixed-clip comparison/fallback.

Source audit already shows important constraints that the runtime POC must confirm:

- startRecordTask creates an independent MP4Muxer/RingReader per call and has no task-extension ID/API;
- startRecordTask does not use the normal MP4Recorder on_record_mp4 finalize path;
- ordinary makeRecorder() can flush an existing GOP Ring into the standard recorder, but Ring creation/lifecycle and absolute timing must be proven;
- rolling tmpfs promotion keeps the ordinary ZLM recorder/hook path and naturally supports unknown Event duration.

Do not implement a custom compressed-video packet ring buffer.

Primary candidate-C test:

```text
Camera
 -> one ZLM recorder
 -> short finalized fragments in bounded tmpfs
 -> on_record_mp4
 -> Event/Trigger overlap selects whole fragments
 -> copy + verify + atomic publish
 -> persistent RecordingSegment + RecordingLocation
```

The recorder stays active while Events only change the promotion window.

Pass condition: stable pre-roll coverage is demonstrated across fragment boundaries and GOP intervals, with bounded measured tmpfs usage and explicit degradation when coverage is unavailable.

## POC-04 — multi-event extension

Example:

```text
event A -> planned end 20:00:20
event B at 20:00:17 -> extend planned end to 20:00:27
```

For the primary rolling-tmpfs candidate, validate that Event A/B/C only extend the effective **promotion window**; they must not start/restart ZLM recording.

Validate:

- Event A/B/C remain separately queryable;
- one source-facing ZLM stream and one normal ZLM recorder remain;
- overlapping finalized tmpfs fragments are promoted once;
- a fragment needed by several Events creates one canonical RecordingSegment/RecordingLocation, not duplicate copies;
- the effective end moves to the latest required post-roll;
- after the final end is covered and finalized, promotion stops while the rolling tmpfs recorder continues.

Also run a small startRecordTask repeated-call comparison so the result records whether the current upstream open repeated-call issue is still reproducible on the tested ZLM commit.

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

Live / recorder / any optional downstream consumer consume ZLM internal streams
```

Pass condition for the Core architecture: multiple downstream consumers attach to ZLM without increasing source-facing main/sub RTSP connections.

Frigate is optional and must not become a prerequisite for freezing the non-AI Core. When the AI feature is enabled, a separate Managed Frigate integration smoke test must repeat the same invariant using the actual Frigate container/config.

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

When all **Core architecture freeze gates** in the classification above pass (or pass with an accepted explicit constraint), change project status from:

```text
V1 Design Freeze Candidate
```

to:

```text
V1 Architecture Frozen
```

POC-02 is handled by its format-selection rule above and optional-feature integration gates do not block a non-enabled Core.

After architecture freeze, changes to component ownership, recording authority, core container boundaries, or storage lifecycle require an ADR.


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
- catalog duration uses actual muxed media metadata rather than assuming exactly 300 seconds;
- current ZLM Hook start_time semantics are measured explicitly;
- a session-first GOP-sized Hook timing bias is corrected through proven same-session next-boundary normalization rather than by widening generic Gap tolerance;
- deliberate source unregister/reconnect splits continuity so normalization never bridges a real outage;
- restarting FastAPI does not deliberately stop an already-running ZLM recorder;
- one intentionally dropped hook is recovered by reconciliation;
- reconciliation is idempotent and creates no duplicate RecordingSegment row for the same physical media;
- ffprobe is not required in the normal successful hook path.

### POC-02 — fMP4 abnormal termination

Pass only if an A/B abnormal-termination test shows that the in-progress fMP4 has materially better recoverability than ordinary MP4 for the tested ZLM configuration and:

- ffprobe can inspect the surviving file;
- ZLM VOD can open the surviving valid coverage;
- FFmpeg can remux/export the surviving valid coverage;
- finalized normal recordings remain browser-playable through the intended playback path;
- no new mandatory repair daemon/process is required;
- the same ordinary-MP4 SIGKILL baseline does not pass all equivalent ffprobe/decode/remux/ZLM-VOD checks.

If fMP4 causes unacceptable VOD/browser/export regressions, do not make it the default even if crash recovery is better.

### POC-03 — EVENT_ONLY pre-roll

For the primary rolling-fragment candidate, whole overlapping fragments are retained, so exact file boundaries do not need to equal the requested pre-roll boundary.

For every Event trigger at T with configured pre-roll P:

```text
earliest promoted media start <= T - P
latest promoted media end    >= final_event_end + post_roll
```

unless source loss, event-delivery delay beyond the retained buffer, or explicit buffer pressure makes that impossible.

Pass only if:

- no custom H.264/H.265 packet ring buffer is required;
- one normal ZLM recorder stays active before/during/after the Event;
- at least 10 repeated triggers at varied positions relative to fragment boundaries satisfy requested coverage;
- tests use at least two GOP/keyframe intervals;
- H.265 is exercised where the test image supports it, otherwise the limitation is explicit;
- whole-fragment extra coverage is measured;
- finalized hook timing is sufficient for canonical RecordingSegment timing;
- tmpfs capacity is explicitly bounded and measured;
- protection/promotion wins races with ephemeral GC;
- unavailable coverage is reported as degraded rather than fabricated;
- control-plane restart can reconstruct finalized ephemeral fragments without a PrebufferFragment table.

Also record comparison results for startRecordTask and ordinary GOP-ring startRecord when practical. A comparison mechanism does not need to pass if the primary candidate passes and its rejection reason is documented.

If no mature ZLM-native mechanism can meet the product target reliably, the architecture decision must be revisited before freeze.

### POC-04 — Multi-event extension

Pass only if:

- two overlapping Events remain two independent Event/RecordingTrigger records;
- only one normal ZLM recorder is active;
- the effective **promotion** deadline extends to the latest required post-roll;
- a third update near the deadline extends promotion again without recorder restart;
- one tmpfs fragment overlapping multiple Events is promoted only once;
- removal/completion of one trigger never causes required media to be garbage-collected while another trigger still needs it;
- after the final required fragment is promoted, rolling prebuffer recording continues without a mode transition;
- the startRecordTask repeated-call comparison is recorded separately and is not mistaken for task extension.

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

Record:

- restore retry-to-READY time;
- first decoded frame wall time after READY;
- prefetch completion time where practical;
- cache bytes before/after eviction and the enforced test limit.

The deterministic WebDAV POC must demonstrate capacity-driven eviction, not merely manual file deletion.

For representative local-LAN remote and Internet/cloud remote tests when available, also record first-play latency. These are operational metrics, not a single universal release threshold.

### POC-08 — Stream sharing / connection count

Pass only if a main + sub camera produces the expected camera-facing connections:

```text
main -> ZLM
sub  -> ZLM
```

and multiple simultaneous downstream consumers consume ZLM-managed/internal streams without creating additional camera RTSP pulls.

For the Core POC, FFmpeg/browser-like readers are acceptable stand-ins because the invariant is source-facing connection count, not consumer identity.

When Managed Frigate is enabled, its feature acceptance must additionally prove:

~~~text
Frigate AI_DETECT input -> ZLM internal stream
source-camera reader count unchanged
~~~

Do not make Frigate image pull/start a prerequisite for users who keep AI disabled.

Verify source-facing connection count with MediaMTX metrics, camera session count, network capture, camera admin UI, or equivalent evidence.

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
