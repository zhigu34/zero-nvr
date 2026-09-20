from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import statistics
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable


RUNTIME = Path("/runtime")
BUSY_TIMEOUT_MS = 5000
RUN_SECONDS = int(os.getenv("POC_SQLITE_RUN_SECONDS", "30"))
PRELOAD_DAYS = int(os.getenv("POC_SQLITE_PRELOAD_DAYS", "30"))
SEGMENT_SECONDS = 300
EVENTS_PER_CAMERA_PER_DAY = int(os.getenv("POC_SQLITE_EVENTS_PER_CAMERA_DAY", "100"))


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


@dataclass
class Metrics:
    latencies_ms: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors: list[dict[str, str]] = field(default_factory=list)
    lock_retries: int = 0
    final_lock_failures: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def timing(self, name: str, seconds: float) -> None:
        with self.lock:
            self.latencies_ms[name].append(seconds * 1000)

    def inc(self, name: str, amount: int = 1) -> None:
        with self.lock:
            self.counters[name] += amount

    def error(self, worker: str, exc: BaseException) -> None:
        with self.lock:
            self.errors.append(
                {
                    "worker": worker,
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return conn


def initialize(path: Path) -> None:
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)

    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        conn.executescript(
            """
            CREATE TABLE cameras (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );

            CREATE TABLE recording_segments (
                id TEXT PRIMARY KEY,
                camera_id TEXT NOT NULL REFERENCES cameras(id),
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX idx_segments_camera_start
                ON recording_segments(camera_id, started_at);
            CREATE INDEX idx_segments_camera_end
                ON recording_segments(camera_id, ended_at);

            CREATE TABLE events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_instance_id TEXT,
                source_event_id TEXT,
                camera_id TEXT REFERENCES cameras(id),
                category TEXT NOT NULL,
                label TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                confidence REAL,
                severity TEXT,
                zone TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source, source_instance_id, source_event_id)
            );
            CREATE INDEX idx_events_camera_start
                ON events(camera_id, started_at);
            CREATE INDEX idx_events_source_start
                ON events(source, started_at);
            CREATE INDEX idx_events_category_start
                ON events(category, started_at);

            CREATE TABLE recording_protections (
                id TEXT PRIMARY KEY,
                camera_id TEXT NOT NULL REFERENCES cameras(id),
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                reason TEXT,
                expires_at TEXT
            );
            CREATE INDEX idx_protection_camera_range
                ON recording_protections(camera_id, started_at, ended_at);

            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_id TEXT,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT,
                camera_id TEXT,
                result TEXT NOT NULL,
                metadata TEXT
            );
            CREATE INDEX idx_audit_occurred
                ON audit_events(occurred_at);

            CREATE TABLE runtime_counters (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            """
        )


def preload(path: Path, cameras: int) -> dict[str, int]:
    now = datetime.now(UTC)
    start = now - timedelta(days=PRELOAD_DAYS)
    camera_ids = [f"cam-{idx:02d}" for idx in range(cameras)]

    with connect(path) as conn:
        conn.executemany(
            "INSERT INTO cameras(id, name) VALUES(?, ?)",
            [(camera_id, camera_id) for camera_id in camera_ids],
        )

        segment_rows = []
        event_rows = []
        segment_count_per_camera = PRELOAD_DAYS * 24 * 60 * 60 // SEGMENT_SECONDS
        event_count_per_camera = PRELOAD_DAYS * EVENTS_PER_CAMERA_PER_DAY

        for cam_idx, camera_id in enumerate(camera_ids):
            for seq in range(segment_count_per_camera):
                seg_start = start + timedelta(seconds=seq * SEGMENT_SECONDS)
                # Introduce deterministic real-world duration jitter around the
                # nominal five-minute target instead of assuming exact 300s.
                jitter_ms = ((seq + cam_idx) % 5 - 2) * 40
                duration_ms = SEGMENT_SECONDS * 1000 + jitter_ms
                seg_end = seg_start + timedelta(milliseconds=duration_ms)
                segment_rows.append(
                    (
                        f"{camera_id}-hist-seg-{seq}",
                        camera_id,
                        iso(seg_start),
                        iso(seg_end),
                        duration_ms,
                        18_000_000 + ((seq + cam_idx) % 1000) * 4096,
                        iso(seg_end),
                    )
                )
                if len(segment_rows) >= 5000:
                    conn.executemany(
                        """
                        INSERT INTO recording_segments(
                            id, camera_id, started_at, ended_at,
                            duration_ms, size_bytes, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        segment_rows,
                    )
                    segment_rows.clear()

            spacing = (PRELOAD_DAYS * 86400) / max(event_count_per_camera, 1)
            for seq in range(event_count_per_camera):
                evt_start = start + timedelta(seconds=seq * spacing + cam_idx * 0.1)
                evt_end = evt_start + timedelta(seconds=2 + (seq % 20))
                event_rows.append(
                    (
                        f"{camera_id}-hist-event-{seq}",
                        "frigate",
                        "poc",
                        f"{camera_id}-{seq}",
                        camera_id,
                        "object",
                        ("person", "vehicle", "cat")[seq % 3],
                        iso(evt_start),
                        iso(evt_end),
                        0.70 + (seq % 25) / 100,
                        ("info", "warning")[seq % 2],
                        ("front", "driveway", None)[seq % 3],
                        "{}",
                        iso(evt_start),
                        iso(evt_end),
                    )
                )
                if len(event_rows) >= 5000:
                    conn.executemany(
                        """
                        INSERT INTO events(
                            id, source, source_instance_id, source_event_id,
                            camera_id, category, label, started_at, ended_at,
                            confidence, severity, zone, metadata,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        event_rows,
                    )
                    event_rows.clear()

        if segment_rows:
            conn.executemany(
                """
                INSERT INTO recording_segments(
                    id, camera_id, started_at, ended_at,
                    duration_ms, size_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                segment_rows,
            )
        if event_rows:
            conn.executemany(
                """
                INSERT INTO events(
                    id, source, source_instance_id, source_event_id,
                    camera_id, category, label, started_at, ended_at,
                    confidence, severity, zone, metadata,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                event_rows,
            )

    return {
        "cameras": cameras,
        "historical_segments": cameras * segment_count_per_camera,
        "historical_events": cameras * event_count_per_camera,
    }


def execute_with_retry(
    path: Path,
    metrics: Metrics,
    worker: str,
    op: Callable[[sqlite3.Connection], None],
    attempts: int = 3,
) -> bool:
    for attempt in range(attempts):
        conn = connect(path)
        try:
            started = time.perf_counter()
            op(conn)
            conn.commit()
            metrics.timing(worker, time.perf_counter() - started)
            return True
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if "locked" in str(exc).lower():
                metrics.lock_retries += 1
                if attempt + 1 < attempts:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                metrics.final_lock_failures += 1
            metrics.error(worker, exc)
            return False
        except Exception as exc:
            conn.rollback()
            metrics.error(worker, exc)
            return False
        finally:
            conn.close()
    return False


def recording_writer(path: Path, cameras: int, stop: threading.Event, metrics: Metrics) -> None:
    seq = 0
    while not stop.is_set():
        now = datetime.now(UTC)
        camera_id = f"cam-{seq % cameras:02d}"
        duration_ms = SEGMENT_SECONDS * 1000 + ((seq % 7) - 3) * 30

        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO recording_segments(
                    id, camera_id, started_at, ended_at,
                    duration_ms, size_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"live-seg-{time.time_ns()}-{seq}",
                    camera_id,
                    iso(now),
                    iso(now + timedelta(milliseconds=duration_ms)),
                    duration_ms,
                    20_000_000 + seq % 100_000,
                    iso(now),
                ),
            )

        if execute_with_retry(path, metrics, "recording_write", op):
            metrics.inc("recording_write_success")
        else:
            metrics.inc("recording_write_failure")
        seq += 1
        stop.wait(0.04)


def event_writer(path: Path, cameras: int, stop: threading.Event, metrics: Metrics) -> None:
    seq = 0
    while not stop.is_set():
        camera_id = f"cam-{seq % cameras:02d}"
        event_key = f"live-{camera_id}-{seq // 2}"
        now = datetime.now(UTC)

        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO events(
                    id, source, source_instance_id, source_event_id,
                    camera_id, category, label, started_at, ended_at,
                    confidence, severity, zone, metadata,
                    created_at, updated_at
                ) VALUES (?, 'frigate', 'load', ?, ?, 'object', 'person',
                          ?, NULL, 0.91, 'info', 'front', '{}', ?, ?)
                ON CONFLICT(source, source_instance_id, source_event_id)
                DO UPDATE SET
                    ended_at = excluded.updated_at,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at
                """,
                (
                    f"evt-{event_key}",
                    event_key,
                    camera_id,
                    iso(now),
                    iso(now),
                    iso(now),
                ),
            )

        if execute_with_retry(path, metrics, "event_upsert", op):
            metrics.inc("event_upsert_success")
        else:
            metrics.inc("event_upsert_failure")
        seq += 1
        stop.wait(0.025)


def audit_writer(path: Path, cameras: int, stop: threading.Event, metrics: Metrics) -> None:
    seq = 0
    while not stop.is_set():
        camera_id = f"cam-{seq % cameras:02d}"
        now = datetime.now(UTC)

        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO audit_events(
                    occurred_at, actor_type, actor_id, action,
                    resource_type, resource_id, camera_id, result, metadata
                ) VALUES (?, 'user', 'poc-admin', 'camera.view',
                          'camera', ?, ?, 'success', '{}')
                """,
                (iso(now), camera_id, camera_id),
            )

        if execute_with_retry(path, metrics, "audit_write", op):
            metrics.inc("audit_write_success")
        else:
            metrics.inc("audit_write_failure")
        seq += 1
        stop.wait(0.05)


def timeline_reader(path: Path, cameras: int, stop: threading.Event, metrics: Metrics, reader_id: int) -> None:
    seq = reader_id
    while not stop.is_set():
        camera_id = f"cam-{seq % cameras:02d}"
        end = datetime.now(UTC) - timedelta(days=(seq % PRELOAD_DAYS))
        start = end - timedelta(hours=6)
        conn = connect(path)
        try:
            started = time.perf_counter()
            segs = conn.execute(
                """
                SELECT id, started_at, ended_at
                FROM recording_segments
                WHERE camera_id = ?
                  AND ended_at > ?
                  AND started_at < ?
                ORDER BY started_at
                """,
                (camera_id, iso(start), iso(end)),
            ).fetchall()
            events = conn.execute(
                """
                SELECT id, started_at, ended_at, category, label
                FROM events
                WHERE camera_id = ?
                  AND started_at >= ?
                  AND started_at < ?
                ORDER BY started_at
                LIMIT 1000
                """,
                (camera_id, iso(start), iso(end)),
            ).fetchall()
            metrics.timing("timeline_query", time.perf_counter() - started)
            metrics.inc("timeline_query_success")
            metrics.inc("timeline_rows_returned", len(segs) + len(events))
        except Exception as exc:
            metrics.error("timeline_query", exc)
            metrics.inc("timeline_query_failure")
        finally:
            conn.close()
        seq += cameras + 1
        stop.wait(0.02)


def event_reader(path: Path, cameras: int, stop: threading.Event, metrics: Metrics, reader_id: int) -> None:
    seq = reader_id
    while not stop.is_set():
        camera_id = f"cam-{seq % cameras:02d}"
        end = datetime.now(UTC)
        start = end - timedelta(days=7)
        conn = connect(path)
        try:
            started = time.perf_counter()
            rows = conn.execute(
                """
                SELECT id, started_at, label, confidence, severity
                FROM events
                WHERE camera_id = ?
                  AND started_at >= ?
                  AND started_at < ?
                  AND category = 'object'
                ORDER BY started_at DESC
                LIMIT 200
                """,
                (camera_id, iso(start), iso(end)),
            ).fetchall()
            metrics.timing("event_query", time.perf_counter() - started)
            metrics.inc("event_query_success")
            metrics.inc("event_rows_returned", len(rows))
        except Exception as exc:
            metrics.error("event_query", exc)
            metrics.inc("event_query_failure")
        finally:
            conn.close()
        seq += cameras + 3
        stop.wait(0.02)


def retention_reader(path: Path, cameras: int, stop: threading.Event, metrics: Metrics) -> None:
    seq = 0
    while not stop.is_set():
        camera_id = f"cam-{seq % cameras:02d}"
        cutoff = datetime.now(UTC) - timedelta(days=14)
        conn = connect(path)
        try:
            started = time.perf_counter()
            rows = conn.execute(
                """
                SELECT id, started_at, ended_at, size_bytes
                FROM recording_segments s
                WHERE s.camera_id = ?
                  AND s.ended_at < ?
                  AND NOT EXISTS (
                    SELECT 1
                    FROM recording_protections p
                    WHERE p.camera_id = s.camera_id
                      AND p.started_at < s.ended_at
                      AND p.ended_at > s.started_at
                  )
                ORDER BY s.ended_at
                LIMIT 500
                """,
                (camera_id, iso(cutoff)),
            ).fetchall()
            metrics.timing("retention_query", time.perf_counter() - started)
            metrics.inc("retention_query_success")
            metrics.inc("retention_rows_returned", len(rows))
        except Exception as exc:
            metrics.error("retention_query", exc)
            metrics.inc("retention_query_failure")
        finally:
            conn.close()
        seq += 1
        stop.wait(0.1)


def backup_worker(path: Path, stop: threading.Event, metrics: Metrics, backups: list[dict]) -> None:
    seq = 0
    while not stop.is_set():
        if stop.wait(5):
            break
        target = RUNTIME / f"{path.stem}-backup-{seq}.sqlite3"
        started = time.perf_counter()
        source = connect(path)
        dest = sqlite3.connect(target)
        try:
            source.backup(dest, pages=256, sleep=0.005)
            dest.commit()
            result = dest.execute("PRAGMA integrity_check").fetchone()[0]
            elapsed = time.perf_counter() - started
            metrics.timing("online_backup", elapsed)
            metrics.inc("backup_success")
            backups.append(
                {
                    "path": str(target),
                    "seconds": elapsed,
                    "integrity_check": result,
                    "size_bytes": target.stat().st_size,
                }
            )
            if result != "ok":
                raise RuntimeError(f"backup integrity_check={result}")
        except Exception as exc:
            metrics.error("online_backup", exc)
            metrics.inc("backup_failure")
        finally:
            source.close()
            dest.close()
        seq += 1


def summarize_latency(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "max_ms": max(values) if values else None,
    }


def file_sizes(path: Path) -> dict[str, int]:
    return {
        "db_bytes": path.stat().st_size if path.exists() else 0,
        "wal_bytes": Path(str(path) + "-wal").stat().st_size
        if Path(str(path) + "-wal").exists()
        else 0,
        "shm_bytes": Path(str(path) + "-shm").stat().st_size
        if Path(str(path) + "-shm").exists()
        else 0,
    }


def run_scenario(cameras: int) -> dict:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    path = RUNTIME / f"sqlite-load-{cameras}.sqlite3"
    initialize(path)

    preload_started = time.perf_counter()
    preloaded = preload(path, cameras)
    preload_seconds = time.perf_counter() - preload_started
    sizes_before = file_sizes(path)

    metrics = Metrics()
    stop = threading.Event()
    backups: list[dict] = []

    workers = [
        threading.Thread(target=recording_writer, args=(path, cameras, stop, metrics), daemon=True),
        threading.Thread(target=event_writer, args=(path, cameras, stop, metrics), daemon=True),
        threading.Thread(target=audit_writer, args=(path, cameras, stop, metrics), daemon=True),
        threading.Thread(target=retention_reader, args=(path, cameras, stop, metrics), daemon=True),
        threading.Thread(target=backup_worker, args=(path, stop, metrics, backups), daemon=True),
    ]
    for idx in range(4):
        workers.append(
            threading.Thread(
                target=timeline_reader,
                args=(path, cameras, stop, metrics, idx),
                daemon=True,
            )
        )
        workers.append(
            threading.Thread(
                target=event_reader,
                args=(path, cameras, stop, metrics, idx),
                daemon=True,
            )
        )

    test_started = time.perf_counter()
    for worker in workers:
        worker.start()

    time.sleep(RUN_SECONDS)
    stop.set()
    for worker in workers:
        worker.join(timeout=10)
    run_seconds = time.perf_counter() - test_started

    sizes_before_checkpoint = file_sizes(path)

    conn = connect(path)
    try:
        checkpoint_started = time.perf_counter()
        checkpoint_row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        checkpoint_seconds = time.perf_counter() - checkpoint_started
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {
            "segments": conn.execute("SELECT COUNT(*) FROM recording_segments").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "audit": conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
        }
    finally:
        conn.close()

    sizes_after_checkpoint = file_sizes(path)

    latencies = {
        name: summarize_latency(values)
        for name, values in metrics.latencies_ms.items()
    }

    timeline_p95 = latencies.get("timeline_query", {}).get("p95_ms")
    event_p95 = latencies.get("event_query", {}).get("p95_ms")
    recording_p95 = latencies.get("recording_write", {}).get("p95_ms")

    hard_pass = (
        integrity == "ok"
        and metrics.final_lock_failures == 0
        and metrics.counters.get("recording_write_failure", 0) == 0
        and metrics.counters.get("event_upsert_failure", 0) == 0
        and metrics.counters.get("audit_write_failure", 0) == 0
        and metrics.counters.get("backup_failure", 0) == 0
        and len(backups) >= 1
    )

    interactive = (
        timeline_p95 is not None
        and event_p95 is not None
        and timeline_p95 < 500
        and event_p95 < 500
    )
    write_latency_ok = recording_p95 is not None and recording_p95 < 500

    if cameras == 8:
        classification = "PASS" if hard_pass and interactive and write_latency_ok else "FAIL"
    else:
        if hard_pass and interactive and write_latency_ok:
            classification = "PASS"
        elif hard_pass:
            classification = "PASS WITH DOCUMENTED HARDWARE/CONFIG REQUIREMENT"
        else:
            classification = "POSTGRESQL RECOMMENDED ABOVE THIS LOAD"

    return {
        "result": classification,
        "camera_count": cameras,
        "run_seconds": run_seconds,
        "configured_run_seconds": RUN_SECONDS,
        "preload_days": PRELOAD_DAYS,
        "preload": preloaded,
        "preload_seconds": preload_seconds,
        "sqlite_version": sqlite3.sqlite_version,
        "python_sqlite_module_version": sqlite3.version,
        "busy_timeout_ms": BUSY_TIMEOUT_MS,
        "journal_mode": "WAL",
        "synchronous": "NORMAL",
        "sizes_before_load": sizes_before,
        "sizes_before_checkpoint": sizes_before_checkpoint,
        "sizes_after_checkpoint": sizes_after_checkpoint,
        "checkpoint": {
            "seconds": checkpoint_seconds,
            "result_row": list(checkpoint_row) if checkpoint_row else None,
        },
        "integrity_check": integrity,
        "counts": counts,
        "counters": dict(metrics.counters),
        "lock_retries": metrics.lock_retries,
        "final_lock_failures": metrics.final_lock_failures,
        "errors": metrics.errors[:100],
        "latencies": latencies,
        "backups": backups,
        "thresholds_used_for_local_classification": {
            "timeline_query_p95_ms_lt": 500,
            "event_query_p95_ms_lt": 500,
            "recording_write_p95_ms_lt": 500,
            "final_lock_failures_eq": 0,
            "recording_event_audit_final_failures_eq": 0,
            "backup_integrity_required": True,
        },
        "note": (
            "Latency thresholds are local POC release gates for the tested hardware, "
            "not universal promises. The raw measurements are authoritative."
        ),
    }


def environment_info() -> dict:
    mem_total_kib = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                mem_total_kib = int(line.split()[1])
                break
    except Exception:
        pass

    cgroup_memory_max = None
    for candidate in (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ):
        try:
            raw = candidate.read_text(encoding="utf-8").strip()
            if raw and raw != "max":
                cgroup_memory_max = int(raw)
                break
        except Exception:
            continue

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "mem_total_kib": mem_total_kib,
        "cgroup_memory_max_bytes": cgroup_memory_max,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cameras", type=int, choices=[8, 16])
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    camera_counts = [8, 16] if args.all or args.cameras is None else [args.cameras]
    results = [run_scenario(count) for count in camera_counts]

    out = {
        "completed_at": iso(datetime.now(UTC)),
        "environment": environment_info(),
        "results": results,
    }
    output = RUNTIME / "sqlite-load-evidence.json"
    output.write_text(
        json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))

    baseline = next(
        (item for item in results if item["camera_count"] == 8),
        None,
    )
    if baseline is not None and baseline["result"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
