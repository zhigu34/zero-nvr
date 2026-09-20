# POC-01 — ZLM Continuous Recording + Hook Indexing

Result: **PASS**

## Purpose

Validate the normal managed recording path and prove that the control plane is not in the media hot path:

~~~text
source -> ZLMediaKit -> fMP4 finalized media
                    -> on_record_mp4
                    -> RecordingSegment + RecordingLocation
~~~

Also validate restart convergence and the deliberately lost-hook fallback.

## Harness

~~~text
poc/zlm-recording/scripts/run.sh
~~~

POC-08 stream-sharing assertions run in the same harness.

## Tested versions

~~~text
GitHub Actions run: 35490737812
job: POC 01
head SHA: 20ae4741b480269bb61b69a8b4b123a46163af02
ZLMediaKit:
  branch: master
  commit: b794772
  buildTime: 2026-09-20T02:21:00
managed recording mode: fMP4
MediaMTX: 1.21.0-ffmpeg
~~~

## Evidence

### FastAPI restart while ZLM records

FastAPI was stopped while the dedicated ZLM recorder remained running.

After FastAPI restarted:

- finalized media overlapped the control-plane downtime;
- one downtime file not yet catalogued was recovered by reconciliation in the final baseline run;
- another segment completed during the unavailable interval and arrived through ZLM's delayed/retried Hook path;
- the recorder remained active;
- a second reconciliation created zero additional rows.

Recorded convergence mechanism:

~~~text
catalog_convergence_mechanism = reconciliation
second_reconcile.recovered_count = 0
~~~

This proves zero-nvr can converge whether ZLM later retries the Hook or reconciliation discovers the finalized file first.

### Normal Hook path

Three consecutive `cam-main` finalized segments were indexed through normal Hook handling:

~~~text
duration_ms:
  9959
  11960
  11960
~~~

The accelerated POC target was 10 seconds, but the actual durations varied with real keyframe/segment boundaries. No fixed 10s/300s duration was assumed.

The normal Hook phase did not increase the ffprobe fallback counter.

### Deliberately dropped Hook

The harness acknowledged one Hook but intentionally skipped catalog insertion.

~~~text
dropped_hook_count = 1
first_reconcile.recovered_count = 1
ffprobe fallback counter increased by 1
second_reconcile.recovered_count = 0
errors = []
~~~

So ffprobe is a recovery fallback, not the normal per-segment indexing path.

### Stream sharing

See POC-08. The source-facing reader count remained:

~~~text
cam_main = 1
cam_sub  = 1
~~~

even while two additional consumers read the ZLM main stream.

## Primary artifact

~~~text
GitHub Actions run: 35490737812
artifact: poc-01-evidence
artifact id: 10598827593
runtime/evidence.json
runtime/api-restart-evidence.json
runtime/poc.db
runtime/recordings/
~~~

## Known limitations

- Segments are accelerated to about 10 seconds for CI. Production normal target remains roughly 300 seconds, while actual finalized media times remain authoritative.
- MediaMTX is a deterministic synthetic camera source only.
- Canonical absolute start/end normalization is validated separately by POC-05 because raw current-ZLM Hook start time has GOP-related bias in some session positions.

## Architecture impact

**Accepted:** ZLMediaKit owns normal recording and continues independently of FastAPI/SQLite availability.

Normal indexing uses `on_record_mp4`; missed/failed metadata delivery converges through Hook retry and/or reconciliation. ffprobe stays outside the successful normal Hook path.
