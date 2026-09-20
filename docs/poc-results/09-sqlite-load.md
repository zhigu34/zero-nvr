# POC-09 — SQLite Load

Result: **PASS**

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
- one AVAILABLE local RecordingLocation for every RecordingSegment;
- one LOCAL recording StorageTarget;
- 100 historical Events per camera per day.

The concurrent phase then runs:

- accelerated RecordingSegment + RecordingLocation inserts in one short transaction;
- Frigate-style Event UPSERTs;
- AuditEvent inserts;
- Timeline queries;
- Event queries;
- retention-candidate queries over AVAILABLE local RecordingLocations plus RecordingProtection overlap checks;
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
- tested CPU/memory/platform information;
- preload row counts, including RecordingLocation count;
- DB/WAL/SHM sizes;
- p50/p95/p99/max latency;
- transient lock retries;
- final lock failures;
- write/query counters;
- backup timing/integrity;
- checkpoint timing/result.

## Tested versions

~~~text
GitHub Actions run: 35490249085
job: POC 09
Python: 3.13.15
SQLite: 3.46.1
journal_mode: WAL
synchronous: NORMAL
busy_timeout: 5000 ms
runner: Ubuntu 24.04.5 / linux amd64
~~~

## Test environment

~~~text
CPU: 4 logical CPUs
host-visible RAM: 16,373,452 KiB (~15.6 GiB)
cgroup memory hard limit: none
load duration: 30 s per scenario
preload history: 30 days
~~~

This hardware description is evidence for the measured result, not a universal minimum requirement.

## Evidence

### 8-camera baseline

~~~text
result = PASS
preloaded RecordingSegments = 69,120
preloaded Events = 24,000
final segments / locations = 69,495 / 69,495
final lock failures = 0
lock retries = 0
errors = []

Event query p95 ≈ 9.67 ms
Timeline query p95 ≈ 7.65 ms
RecordingSegment+RecordingLocation write p95 ≈ 197.03 ms

online backups completed = 5
backup integrity_check = ok
main DB integrity_check = ok

DB after checkpoint ≈ 52.4 MB
WAL after TRUNCATE checkpoint = 0
checkpoint ≈ 0.055 s
~~~

### 16-camera extended target

~~~text
result = PASS
preloaded RecordingSegments = 138,240
preloaded Events = 48,000
final segments / locations = 138,518 / 138,518
final lock failures = 0
lock retries = 0
errors = []

Event query p95 ≈ 22.91 ms
Timeline query p95 ≈ 15.56 ms
RecordingSegment+RecordingLocation write p95 ≈ 354.26 ms

online backups completed = 4
backup integrity_check = ok
main DB integrity_check = ok

DB after checkpoint ≈ 104.2 MB
WAL after TRUNCATE checkpoint = 0
checkpoint ≈ 0.018 s
~~~

Primary artifact:

~~~text
GitHub Actions run: 35490249085
artifact: poc-09-evidence
artifact id: 10598403979
runtime/sqlite-load-evidence.json
~~~

### Performance observation

The current synthetic retention-candidate query is deliberately broad and was much slower than interactive reads:

~~~text
8 cameras retention query p95  ≈ 5.84 s
16 cameras retention query p95 ≈ 10.21 s
~~~

This does **not** invalidate SQLite because retention is a background lifecycle job and the concurrent recording/Event/Timeline workload remained healthy with zero lock failures.

It does create an implementation requirement:

- retention runs through Huey/background work, never a synchronous user-request hot path;
- scan/delete decisions are bounded/paginated in batches;
- query/index shape is optimized against the real frozen schema before release;
- long retention scans do not hold write transactions across file/rclone operations.

## Architecture impact

**SQLite + WAL remains the accepted default production database.**

The 8-camera baseline passed comfortably, and the 16-camera extended target also passed the local write/query thresholds on the tested 4-CPU runner without Redis or PostgreSQL.

PostgreSQL remains an optional scale-up/deployment choice, not a prerequisite for a normal production installation.

The result does not define minimum hardware memory for zero-nvr as a whole; full-application resource validation remains separate.
