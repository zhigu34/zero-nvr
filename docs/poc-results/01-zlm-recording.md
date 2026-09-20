# POC-01 — ZLM Continuous Recording + Hook Indexing

Result: **PASS**

## Purpose

Validate the normal recording path:

~~~text
source
-> ZLMediaKit
-> finalized MP4/fMP4
-> on_record_mp4
-> RecordingSegment + RecordingLocation
~~~

and prove:

- FastAPI/control-plane restart does not deliberately stop an already-running ZLM recorder;
- normal segment indexing uses ZLM finalize metadata rather than ffprobe;
- lost hooks are recoverable idempotently;
- ZLM remains the source-facing media bus.

## Harness

~~~text
poc/zlm-recording/scripts/run.sh
~~~

Passing runtime execution:

~~~text
GitHub Actions run: 35490899825
job: POC 01
~~~

## Tested versions

~~~text
ZLMediaKit:
  branch: master
  commit: b794772
  buildTime: 2026-09-20T02:21:00

MediaMTX: 1.21.0-ffmpeg
Docker Engine: 28.0.4
Docker Compose: v2.38.2
runner: Ubuntu 24.04.5 / linux amd64
~~~

POC segmentation was accelerated to 10 seconds. Product production segmentation remains separately configurable and must never be assumed from the POC duration.

## Evidence

### Control-plane restart

A dedicated ZLM stream/recorder was started before FastAPI was stopped.

FastAPI downtime:

~~~text
start:    2026-09-20T05:09:12Z
end:      2026-09-20T05:09:32Z
duration: 20.0 s
~~~

After FastAPI returned:

~~~text
ZLM recorder active = true
~~~

Media overlapping the control-plane downtime existed and converged into the catalog by two valid paths:

~~~text
2026-09-20T05:09:12Z .. 05:09:19.960Z
  source = delayed/retried hook

2026-09-20T05:09:20Z .. 05:09:28Z
  source = reconciliation
~~~

The first reconciliation recovered exactly one finalized file:

~~~text
/recordings/record/poc/api-restart-poc/2026-09-20/2026-09-20-05-09-20-3.mp4
recovered_count = 1
errors = []
~~~

The second reconciliation was idempotent:

~~~text
recovered_count = 0
errors = []
~~~

This demonstrates that the zero-nvr API process is not required for ZLM to continue recording.

### Normal hook path

The normal `cam-main` phase produced finalized segments through `on_record_mp4`.

Representative actual durations:

~~~text
9.959 s
11.960 s
11.959 s
~~~

The harness intentionally does not assume the configured target duration is the actual finalized duration.

The ffprobe fallback counter did not increase during normal Hook indexing.

### Deliberately lost hook

The harness then acknowledged but intentionally skipped one recording Hook.

Before the deliberate loss/recovery phase:

~~~text
dropped_hook_count = 0
ffprobe_calls = 1   # earlier API-restart reconciliation
~~~

After the deliberate loss/reconciliation phase:

~~~text
dropped_hook_count = 1
ffprobe_calls = 2
~~~

The missing file was recovered through reconciliation, and the second reconciliation created no duplicate row.

Therefore ffprobe remains a recovery fallback, not the normal per-segment indexing path.

### Physical-copy uniqueness

The POC catalog enforced one unique physical object path per RecordingLocation.

No duplicate object path was created by Hook retry/reconciliation.

### Stream sharing

POC-08 shares this run and independently records the reader-count result.

Before additional downstream readers:

~~~text
cam_main source readers = 1
cam_sub  source readers = 1
~~~

With two additional readers attached to ZLM:

~~~text
cam_main source readers = 1
cam_sub  source readers = 1
~~~

## Artifact

~~~text
GitHub Actions run: 35490899825
artifact: poc-01-evidence
artifact id: 10598049983
SHA256: eaea47b3a2a26cb3ddebec1a6712c01d8df5c39f344feabb726035fff1e3f95a
~~~

Primary files:

~~~text
runtime/evidence.json
runtime/api-restart-evidence.json
runtime/poc.db
runtime/docker-compose.log
runtime/recordings/
~~~

## Known limitations

- The deterministic source is synthetic; real-camera compatibility remains normal camera-integration testing.
- The test uses accelerated segment duration.
- Hook delivery after API restart can converge either through ZLM retry/delayed delivery or reconciliation. Production correctness must support both and remain idempotent.
- POC-05 defines the stronger canonical wall-clock normalization rule; raw Hook `start_time` is not blindly used as final Timeline truth.
- POC-02 separately selects fMP4 as the default recording container mode.

## Architecture impact

**Accepted.**

V1 recording authority is frozen as:

~~~text
Camera
  -> ZLMediaKit
  -> normal ZLM recorder
  -> finalized file
  -> on_record_mp4 fast path
  -> RecordingSegment + RecordingLocation

lost/missed Hook
  -> reconciliation
  -> ffprobe only when required for recovery
~~~

The FastAPI/worker control plane is not the media hot path.

Do not introduce:

- a permanent FFmpeg recorder;
- a second RTSP reconnect engine;
- polling ffprobe for every segment;
- a mandatory RecordingSession/RecordingIntent runtime table.

ZLMediaKit remains responsible for source pull/reconnect and normal recording.
