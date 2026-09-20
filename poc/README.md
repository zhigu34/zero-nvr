# Design-Freeze POCs

This directory contains **disposable architecture-validation harnesses**.

They are not production zero-nvr services.

Current project status remains:

~~~text
V1 Design Freeze Candidate
~~~

All result documents are still `NOT RUN` until a real Docker host executes the harnesses and evidence is copied into `docs/poc-results/`.

## Unified runner

From repository root:

~~~bash
sh poc/run-design-freeze.sh 01
sh poc/run-design-freeze.sh 03
sh poc/run-design-freeze.sh 09
sh poc/run-design-freeze.sh all
~~~

Selectors:

| Selector | Harness |
|---|---|
| 01 / 08 | ZLM recording, FastAPI restart, hook recovery, stream sharing |
| 02 | fMP4 abnormal termination |
| 03 / 04 | EVENT_ONLY pre-roll and overlapping Event extension |
| 05 / 06 | timeline precision and ZLM VOD seek |
| 07 | rclone remote restore playback |
| 09 | SQLite 8/16-camera mixed load |
| 10 | reconciliation/fault convergence |

Paired selectors share one runtime harness and are not executed twice by `all`.

## Harness groups

~~~text
poc/zlm-recording/
  media / recording / playback / remote / reconciliation POCs

poc/sqlite-load/
  SQLite load POC
~~~

## Result source of truth

See:

- [POC status matrix](../docs/poc-results/README.md)
- [POC plan / quantitative pass criteria](../docs/plans/01-design-freeze-poc.md)

A runner returning zero is necessary but not sufficient for architecture freeze. The result document must also record:

- tested component versions;
- environment/hardware;
- evidence files;
- measured values;
- known limitations;
- architecture impact.

## Guardrails

POC code must not quietly become production architecture.

Do not introduce just for a POC:

- a permanent FFmpeg recorder;
- a custom RTSP reconnect engine;
- a custom packet ring;
- Redis/Celery;
- StoragePool;
- generic event bus;
- generic incident/escalation engine.

The purpose is to validate the reuse-first boundaries already documented in the project baseline.
