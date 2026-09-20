# SQLite Load POC

Disposable design-freeze harness for **POC-09**.

It validates SQLite as the default zero-nvr database under an intentionally accelerated mixed workload.

## What it exercises

Before the concurrent run it preloads the equivalent of:

- 30 days of 5-minute RecordingSegment rows for every camera;
- 100 Events per camera per day.

Then, concurrently:

- accelerated RecordingSegment inserts;
- Frigate-style Event UPSERTs;
- AuditEvent inserts;
- four Timeline query workers;
- four Event query workers;
- retention-candidate queries;
- SQLite Online Backup while writes continue.

Database mode:

~~~text
WAL
synchronous=NORMAL
busy_timeout=5000ms
~~~

No Redis and no PostgreSQL are involved.

## Run

~~~bash
cd poc/sqlite-load
sh ./run.sh
~~~

The runner executes both:

~~~text
8 cameras
16 cameras
~~~

using Python 3.13 in a one-off container.

Default workload duration is 30 seconds per scenario after preload.

Override in the environment if a longer soak is desired:

~~~text
POC_SQLITE_RUN_SECONDS=120
POC_SQLITE_PRELOAD_DAYS=90
~~~

## Evidence

~~~text
runtime/sqlite-load-evidence.json
runtime/sqlite-load-8.sqlite3
runtime/sqlite-load-16.sqlite3
runtime/*-backup-*.sqlite3
~~~

The result records:

- SQLite version;
- DB/WAL/SHM sizes;
- p50/p95/p99/max latency by operation;
- transient lock retries;
- final lock failures;
- row counts;
- Online Backup integrity;
- WAL checkpoint timing.

## Local classification thresholds

The harness uses 500ms p95 as a practical local interactivity/write threshold for:

- Timeline query;
- Event query;
- RecordingSegment write.

These are **not universal hardware guarantees**.

Raw measurements are authoritative and should be recorded in the POC result document.

For 16 cameras, the harness may classify:

~~~text
PASS
PASS WITH DOCUMENTED HARDWARE/CONFIG REQUIREMENT
POSTGRESQL RECOMMENDED ABOVE THIS LOAD
~~~

Do not demote SQLite based on assumptions.
