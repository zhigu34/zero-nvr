# POC-10 — Recovery Reconciliation

Result: **PASS**

## Purpose

Prove that zero-nvr converges to an explainable catalog after control-plane/process/database faults without deleting valid media or guessing ambiguous files into place.

## Harness

~~~text
poc/zlm-recording/scripts/run-reconciliation.sh
~~~

## Faults injected

1. One on_record_mp4 hook is deliberately acknowledged but not indexed.
2. FastAPI is stopped for about 18 seconds while ZLM keeps recording.
3. SQLite holds a BEGIN IMMEDIATE write lock for about 22 seconds while ZLM continues to finalize media and hook delivery encounters DB contention.
4. One catalogued RecordingLocation file is moved aside, leaving stale metadata.
5. One valid MP4 is copied into a normal ZLM recording hierarchy with a provable stream/time identity but no catalog row.
6. One valid MP4 is copied into an ambiguous orphan path with no trustworthy camera/stream identity.
7. Reconciliation is intentionally terminated after its first committed mutation, then started again.

## Required behavior

- the deliberately dropped hook's exact object_path becomes one AVAILABLE RecordingLocation after reconciliation;
- the exact FastAPI downtime window is recorded and must contain AVAILABLE catalog coverage after reconciliation;
- at least one reconcile-sourced segment must land in/near the FastAPI downtime window, proving media finalized while the control plane was unavailable;
- the exact SQLite write-lock window is recorded and must contain AVAILABLE catalog coverage after convergence;
- valid media is never deleted merely because DB metadata is stale;
- missing catalogued media becomes RecordingLocation state MISSING;
- a valid orphan whose stream/time identity can be proven is recovered into one RecordingSegment + RecordingLocation;
- the recovered media is playable through the normal ZLM VOD path;
- ambiguous media remains on disk and diagnosable, but is not guessed into the catalog;
- lost hooks / API downtime / DB-write downtime are recoverable by scanning finalized media;
- restarting the reconciliation process after a committed mutation continues safely;
- a second full reconciliation performs zero mutations;
- duplicate RecordingLocation object paths are not created;
- the normal ZLM recorder remains active after recovery.

## Worker restart interpretation

The current design-freeze repository does not yet contain the production Huey worker.

This POC therefore simulates worker/process death at the reconciliation mutation boundary by intentionally terminating the reconciliation process after one committed change and restarting it against the same DB/filesystem.

Once the real Huey worker is implemented, repeat a kill/restart smoke test around the same idempotent reconciliation job. Do not build a POC-only custom job queue just to imitate Huey.

## Expected evidence

~~~text
poc/zlm-recording/runtime/reconciliation-evidence.json
poc/zlm-recording/runtime/api-downtime.json
poc/zlm-recording/runtime/reconciliation-runs.json
poc/zlm-recording/runtime/reconciliation-fixtures.json
poc/zlm-recording/runtime/reconciliation-simulated-crash.json
poc/zlm-recording/runtime/db-lock-started.json
poc/zlm-recording/runtime/db-lock-finished.json
poc/zlm-recording/runtime/reconcile-docker-compose.log
~~~

## Tested versions

~~~text
GitHub Actions run: 35489849518
job: POC 10
ZLMediaKit:
  branch: master
  commit: b794772
  buildTime: 2026-09-20T02:21:00
Docker Engine: 28.0.4
Docker Compose: v2.38.2
runner: Ubuntu 24.04.5 / linux amd64
~~~

## Test environment

GitHub-hosted Ubuntu 24.04.5 runner:

~~~text
kernel: 6.17.0-1022-azure
architecture: x86_64
host-visible RAM: ~15 GiB
~~~

The test used the same deterministic MediaMTX -> ZLMediaKit recording path as the other media POCs.

## Evidence

Runtime result:

~~~text
result = PASS

baseline:
  finalized hook segments = 3
  deliberately dropped hook count = 1
  ffprobe calls before reconciliation = 0

faults exercised:
  FastAPI/control-plane restart
  SQLite BEGIN IMMEDIATE write lock = 22 s
  missed hook(s) while DB/control path unavailable
  stale catalog row whose file was removed
  provable orphan media under canonical ZLM recording hierarchy
  ambiguous orphan at /recordings/orphans/mystery.mp4
  reconciliation process death after one committed mutation

first converging reconciliation:
  recovered = 4 files
  errors = []
  ambiguous = mystery.mp4
  changes = 4

second reconciliation:
  changes = 0
  recovered = []
  errors = []
  ambiguous file remains diagnosable/preserved

catalog/fidelity:
  stale location state = MISSING
  proven orphan state = AVAILABLE
  ambiguous orphan cataloged = false
  ambiguous orphan preserved = true
  valid guard file preserved = true
  valid guard SHA-256 unchanged = true

final catalog:
  segment_count = 11
  hook_segment_count = 7
  reconciled_segment_count = 4
  location_count = 11
  recorder_active = true

recovered media:
  ZLM RTSP VOD decode = PASS
~~~

Primary artifact:

~~~text
GitHub Actions artifact:
  poc-10-evidence
  run 35489849518

runtime/reconciliation-evidence.json
runtime/reconciliation-runs.json
runtime/reconcile-docker-compose.log
~~~

## Known limitations

- This POC validates the reconciliation policy on deterministic local ZLM media. Remote RecordingLocation reconciliation has separate storage-adapter semantics.
- The POC intentionally preserves an ambiguous orphan instead of guessing its Camera/segment identity. A production UI/doctor flow still needs to expose such ambiguous objects clearly.
- Timing normalization of raw ZLM Hook timestamps is governed separately by POC-05/Spec 0004; this POC validates convergence/identity safety, not final Timeline precision.

## Architecture impact

**The ADR 0008 reconciliation model is accepted.**

V1 may keep the database outside the live media write path and rely on idempotent reconciliation after control-plane/worker/database interruptions.

Accepted behavior:

~~~text
valid extra media + provable identity
  -> recover catalog/RecordingLocation

catalog says AVAILABLE but file absent
  -> mark MISSING / explain

ambiguous media
  -> preserve and report
  -> never guess/delete

rerun
  -> zero additional mutations once converged
~~~

A custom persistent UploadJob/RecordingSession/runtime-history model is not required to achieve convergence.
