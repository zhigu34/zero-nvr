# Design-Freeze POC Status

Project status remains:

~~~text
V1 Design Freeze Candidate
~~~

A committed harness is **not** a passing result. A POC moves to PASS only from reviewed runtime evidence; rerun-required harness failures are recorded separately from architecture failures.

## Status matrix

| POC | Purpose | Runner | Current result |
|---|---|---|---|
| 01 | ZLM recording / hook indexing / API restart / reconciliation | `poc/zlm-recording/scripts/run.sh` | RERUN REQUIRED — control-plane continuity assertion relaxed to accept valid Hook retry or reconciliation; clean rerun required |
| 02 | fMP4 abnormal termination recovery | `poc/zlm-recording/scripts/run-fmp4-crash.sh` | PASS — fMP4 materially outperformed interrupted ordinary MP4 |
| 03 | EVENT_ONLY pre-roll | `poc/zlm-recording/scripts/run-event-preroll.sh` | PASS |
| 04 | overlapping Event extension / deduplicated promotion | same as POC-03 | PASS |
| 05 | wall-clock timeline precision / real Gap | `poc/zlm-recording/scripts/run-timeline-playback.sh` | RERUN REQUIRED — first run exposed raw ZLM Hook start-time GOP bias; timing normalization added |
| 06 | ZLM VOD seek | same as POC-05 | RERUN REQUIRED — first run stopped at POC-05 timing gate before seek checks |
| 07 | rclone remote restore playback / bounded cache | `poc/zlm-recording/scripts/run-remote-restore.sh` | PASS |
| 08 | ZLM stream sharing / source connection count | same as POC-01 | RERUN REQUIRED — MediaMTX metrics-auth harness issue fixed; reader-count assertion still needs clean rerun |
| 09 | SQLite 8/16-camera mixed load | `poc/sqlite-load/run.sh` | PASS — both 8-camera baseline and 16-camera extended target passed |
| 10 | fault/reconciliation convergence | `poc/zlm-recording/scripts/run-reconciliation.sh` | PASS |

## Gate meaning

The numbered POCs have different meanings:

- **Core freeze gates:** 01, 03, 04, 05, 06, 07, 08-Core, 09, 10.
- **Format-selection gate:** 02. A failure means ordinary MP4 stays the default; it does not change ZLM recording ownership by itself.
- **Optional-feature gates:** real Managed Frigate/OpenList/coturn/etc. smoke tests are required only when those features are enabled/declared production-ready, not for a non-AI/non-OpenList Core deployment.

See [V1 Design-Freeze POC Plan](../plans/01-design-freeze-poc.md) for the exact rules.

## Aggregate runner

Run all current design-freeze harnesses from the repository root:

~~~bash
sh ./poc/run-all.sh
~~~

Per-group compact evidence is archived under:

~~~text
poc/runtime-results/<UTC timestamp>/
~~~

The script records runner exit codes and preserves later independent results even if an earlier group fails.

## Evidence rule

Each result document must contain:

~~~text
Result: PASS | FAIL | PASS WITH CONSTRAINTS
Tested versions:
Test environment:
Evidence:
Known limitations:
Architecture impact:
~~~

Do not replace `NOT RUN` with PASS based on:

- source review;
- a successful container build;
- one manually viewed video;
- assumptions about ZLMediaKit/rclone/SQLite behavior.

The quantitative pass criteria are defined in:

- [V1 Design-Freeze POC Plan](../plans/01-design-freeze-poc.md)

## Architecture freeze rule

The project may move to:

~~~text
V1 Architecture Frozen
~~~

only after:

1. all Core architecture freeze gates have real PASS or accepted PASS WITH CONSTRAINTS results;
2. failed/conditional results have their constraints reflected in product/deployment docs;
3. POC-02 has a documented container-format decision even if the result is to keep ordinary MP4;
4. any result that changes component ownership, recording authority, Core container boundaries, storage lifecycle, or database-default policy is resolved through an ADR;
5. [V1 Schema Freeze](../plans/02-v1-schema-freeze.md) remains consistent with the measured architecture;
6. [V1 API / Module Freeze](../plans/03-v1-api-module-freeze.md) remains consistent with the measured architecture.

## Current architecture assumptions under test

The harnesses intentionally validate these assumptions rather than silently treating them as facts:

- ZLM normal MP4/fMP4 recording and hook metadata are sufficient for canonical RecordingSegment indexing;
- FastAPI/worker restart does not need to be in the recording hot path;
- EVENT_ONLY can be implemented without a custom packet ring or second recorder;
- ZLM VOD is adequate for historical segment playback/seek;
- rclone restore-to-cache is sufficient without FUSE;
- ZLM remains the only camera-facing media pull in Managed mode;
- SQLite remains first-class for the intended default deployment scale;
- reconciliation can recover from stale/missing metadata without deleting valid media.

## Result documents

- [POC-01](01-zlm-recording.md)
- [POC-02](02-fmp4-crash.md)
- [POC-03](03-event-preroll.md)
- [POC-04](04-multi-event-extension.md)
- [POC-05](05-timeline-precision.md)
- [POC-06](06-zlm-vod-seek.md)
- [POC-07](07-remote-restore.md)
- [POC-08](08-stream-sharing.md)
- [POC-09](09-sqlite-load.md)
- [POC-10](10-reconciliation.md)
