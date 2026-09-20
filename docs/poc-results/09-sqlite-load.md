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

The harness now uses 500ms p95 as a local test threshold for Timeline query, Event query, RecordingSegment write, **and retention-candidate scan latency**. Raw measurements remain authoritative.

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
GitHub Actions run: 35490737812
job: POC 09
head SHA: 20ae4741b480269bb61b69a8b4b123a46163af02
Python: 3.13.15
SQLite: 3.46.1
journal_mode: WAL
synchronous: NORMAL
busy_timeout: 5000 ms
runner: Ubuntu / linux amd64
~~~

## Test environment

~~~text
CPU: 4 logical CPUs
host-visible RAM: 16,372,440 KiB (~15.6 GiB)
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
final segments / locations = 69,817 / 69,817
final lock failures = 0
lock retries = 0
errors = []

Event query p95 ≈ 5.54 ms
Timeline query p95 ≈ 4.80 ms
RecordingSegment+RecordingLocation write p95 ≈ 7.46 ms
Event UPSERT p95 ≈ 5.70 ms
Retention candidate query p95 ≈ 12.11 ms

online backups completed = 2
backup integrity_check = ok
main DB integrity_check = ok
WAL after TRUNCATE checkpoint = 0
checkpoint ≈ 0.005 s
~~~

### 16-camera extended target

~~~text
result = PASS
preloaded RecordingSegments = 138,240
preloaded Events = 48,000
final segments / locations = 138,949 / 138,949
final lock failures = 0
lock retries = 0
errors = []

Event query p95 ≈ 5.14 ms
Timeline query p95 ≈ 4.47 ms
RecordingSegment+RecordingLocation write p95 ≈ 7.72 ms
Event UPSERT p95 ≈ 4.81 ms
Retention candidate query p95 ≈ 11.31 ms

online backups completed = 1
backup integrity_check = ok
main DB integrity_check = ok
WAL after TRUNCATE checkpoint = 0
checkpoint ≈ 0.012 s
~~~

### Retention-query optimization

The first run had exposed an unacceptable planner choice:

~~~text
8 cameras retention p95  ≈ 5.84 s
16 cameras retention p95 ≈ 10.21 s
~~~

The frozen query/index shape was then changed to drive the scan from RecordingSegment camera/end-time order and point-lookup the physical location:

~~~text
RecordingSegment(camera_id, ended_at, started_at, id)
RecordingLocation(recording_segment_id, storage_target_id, state)
~~~

SQLite planner statistics are refreshed after the bulk historical import.

The rerun recorded:

~~~text
8 cameras retention p95  ≈ 12.11 ms
16 cameras retention p95 ≈ 11.31 ms
~~~

Representative EXPLAIN QUERY PLAN:

~~~text
SEARCH s USING COVERING INDEX idx_segments_camera_end_cover
  (camera_id=? AND ended_at<?)
CORRELATED SCALAR SUBQUERY
SEARCH p USING COVERING INDEX idx_protection_camera_range
SEARCH l USING INDEX idx_locations_segment_target_state
  (recording_segment_id=? AND storage_target_id=? AND state=?)
~~~

This closes the seconds-scale retention-query issue and satisfies the new local `retention_query p95 < 500 ms` gate by a wide margin.

### Backup observation

SQLite Online Backup remained correct while writes/queries continued. On this shared CI runner it was intentionally not treated as an interactive-latency path:

~~~text
8-camera backup wall time: ~7.4 s and ~13.0 s
16-camera backup wall time: ~26.2 s
integrity_check: ok
~~~

Backup stays background work and must never hold recording/network/storage work inside a database write transaction.

Primary artifact:

~~~text
GitHub Actions run: 35490737812
artifact: poc-09-evidence
artifact id: 10597754860
runtime/sqlite-load-evidence.json
~~~

## Architecture impact

**Accepted: SQLite + WAL is the V1 default production database.**

The representative 8-camera baseline and 16-camera extended target both passed:

- short concurrent recording/Event/Audit writes;
- Timeline/Event reads;
- the tightened retention p95 gate;
- online backup integrity;
- WAL checkpoint/truncation;
- zero final lock failures;
- without Redis or PostgreSQL.

Required implementation details are now frozen:

- short transactions;
- WAL + busy timeout;
- retention-oriented composite indexes from the Schema Freeze;
- planner-statistics refresh after large imports/migrations;
- bounded background retention scans;
- SQLite Online Backup for system backup snapshots.

PostgreSQL remains an optional scale-up/deployment choice, not a prerequisite for a normal production installation.

The result does not define minimum hardware memory for zero-nvr as a whole; full-application resource validation remains separate.
