# POC-01 — ZLM Continuous Recording + Hook Indexing

Result: **NOT RUN**

## Purpose

Validate:

```text
source
-> ZLMediaKit
-> finalized MP4
-> on_record_mp4
-> RecordingSegment + RecordingLocation
```

and prove that a lost hook is recoverable idempotently without making ffprobe part of normal per-segment indexing.

## Harness

```text
poc/zlm-recording/
```

The harness is committed, but no runtime evidence has been produced by this conversation environment.

## Required evidence before PASS

- actual ZLM branch/commit/build time from `/index/api/version`;
- actual runtime container/image identity;
- at least three consecutive finalized hook-indexed segments;
- start/end/duration derived from actual hook metadata;
- zero ffprobe calls on the normal hook path;
- one deliberately dropped hook;
- reconciliation discovers the unindexed finalized file;
- ffprobe is used only for recovery fallback;
- second reconciliation creates zero additional rows;
- no duplicate RecordingLocation object paths;
- representative logs plus `runtime/evidence.json`.

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

Expected generated files:

```text
poc/zlm-recording/runtime/evidence.json
poc/zlm-recording/runtime/docker-compose.log
poc/zlm-recording/runtime/poc.db
poc/zlm-recording/runtime/recordings/
```

Generated runtime artifacts are intentionally gitignored.

## Known limitations

The harness uses 10-second segments to accelerate testing. Production segmentation remains nominally ~300 seconds and must still use actual finalized-media timestamps.

MediaMTX is a synthetic POC source only.

## Architecture impact

None yet. Do not freeze the recording path based on an unexecuted harness.
