# POC-10 — Recovery Reconciliation

Result: **NOT RUN**

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
poc/zlm-recording/runtime/reconciliation-runs.json
poc/zlm-recording/runtime/reconciliation-fixtures.json
poc/zlm-recording/runtime/reconciliation-simulated-crash.json
poc/zlm-recording/runtime/db-lock-started.json
poc/zlm-recording/runtime/db-lock-finished.json
poc/zlm-recording/runtime/reconcile-docker-compose.log
~~~

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

## Architecture impact

Pending execution.
