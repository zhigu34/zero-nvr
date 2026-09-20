# POC-09 — SQLite Load

Result: **NOT RUN**

## Purpose

Validate SQLite + WAL as the default production database for the intended zero-nvr deployment size instead of assuming PostgreSQL is required.

## Harness

~~~text
poc/sqlite-load/
~~~

Run:

~~~bash
cd poc/sqlite-load
sh ./run.sh
~~~

## Scenarios

The harness executes:

~~~text
8-camera baseline
16-camera extended target
~~~

Each scenario preloads:

- 30 days of nominal 5-minute RecordingSegment rows per camera;
- 100 historical Events per camera per day.

The concurrent phase then runs:

- accelerated RecordingSegment inserts;
- Frigate-style Event UPSERTs;
- AuditEvent inserts;
- Timeline queries;
- Event queries;
- retention-candidate queries;
- SQLite Online Backup while writes continue.

Database mode:

~~~text
journal_mode = WAL
synchronous = NORMAL
busy_timeout = 5000ms
~~~

No Redis or PostgreSQL service is used.

## Required checks

### 8-camera baseline

PASS requires:

- zero final database-lock failures;
- zero lost RecordingSegment/Event/Audit writes;
- no backup failures;
- backup PRAGMA integrity_check = ok;
- main DB integrity_check = ok;
- Timeline/Event p95 remains interactively usable on the tested hardware;
- RecordingSegment write p95 remains acceptable;
- WAL/checkpoint behavior remains bounded.

The harness uses 500ms p95 as a local test threshold for Timeline/Event query and recording write latency. Raw measurements remain authoritative.

### 16-camera target

Record the same measurements and classify:

~~~text
PASS
PASS WITH DOCUMENTED HARDWARE/CONFIG REQUIREMENT
POSTGRESQL RECOMMENDED ABOVE THIS LOAD
~~~

A 16-camera limitation does not automatically demote SQLite from the default 8-camera/small-deployment path.

The runner exits non-zero when the 8-camera baseline is not PASS. A 16-camera result may still be PASS WITH DOCUMENTED HARDWARE/CONFIG REQUIREMENT or POSTGRESQL RECOMMENDED ABOVE THIS LOAD without invalidating the measured 8-camera default target.

## Expected evidence

~~~text
poc/sqlite-load/runtime/sqlite-load-evidence.json
poc/sqlite-load/runtime/sqlite-load-8.sqlite3
poc/sqlite-load/runtime/sqlite-load-16.sqlite3
poc/sqlite-load/runtime/*-backup-*.sqlite3
~~~

Evidence records:

- host/container platform, architecture, CPU count, memory visibility/limit;
- Python and SQLite version;
- preload row counts;
- DB/WAL/SHM sizes;
- p50/p95/p99/max latency;
- transient lock retries;
- final lock failures;
- write/query counters;
- backup timing/integrity;
- checkpoint timing/result.

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

## Architecture impact

Pending execution.

Do not replace SQLite as the default based on assumption. Change database-default policy only from measured evidence plus an ADR.
