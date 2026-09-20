from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "http://127.0.0.1:8000"
ZLM = os.getenv("ZLM_BASE_URL", "http://zlm")
ZLM_SECRET = os.environ["ZLM_API_SECRET"]
DB_PATH = Path(os.getenv("DB_PATH", "/runtime/poc.db"))
RECORDING_ROOT = Path(os.getenv("RECORDING_ROOT", "/recordings"))
VOD_ROOT = Path("/vod")
RUNTIME = Path("/runtime")
STATE = RUNTIME / "reconciliation-state.json"
RUN_LOG = RUNTIME / "reconciliation-runs.json"
EVIDENCE = RUNTIME / "reconciliation-evidence.json"
STREAM = "reconcile-poc"
SEGMENT_SECONDS = 6


class SimulatedCrash(RuntimeError):
    pass


def iso(ts: float | datetime) -> str:
    if isinstance(ts, datetime):
        dt = ts.astimezone(UTC)
    else:
        dt = datetime.fromtimestamp(ts, tz=UTC)
    return dt.isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def request_json(url: str, *, method: str = "GET", timeout: float = 10) -> dict[str, Any]:
    req = Request(url, method=method)
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def zlm_api(name: str, **params: Any) -> dict[str, Any]:
    query = urlencode({"secret": ZLM_SECRET, **params})
    return request_json(f"{ZLM}/index/api/{name}?{query}")


def wait_until(description: str, predicate, timeout: float, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception as exc:
            last = repr(exc)
        time.sleep(interval)
    raise AssertionError(f"timeout waiting for {description}; last={last!r}")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def segments() -> list[dict[str, Any]]:
    return [
        item
        for item in request_json(f"{API}/debug/segments")["items"]
        if item["stream"] == STREAM
    ]


def hook_summary() -> dict[str, Any]:
    return request_json(f"{API}/debug/summary")


def recorder_active() -> bool:
    response = zlm_api(
        "isRecording",
        type=1,
        vhost="__defaultVhost__",
        app="poc",
        stream=STREAM,
    )
    return response.get("code") == 0 and bool(response.get("status"))


def add_proxy() -> str:
    response = zlm_api(
        "addStreamProxy",
        vhost="__defaultVhost__",
        app="poc",
        stream=STREAM,
        url="rtsp://mediamtx:8554/cam_main",
        rtp_type=0,
        retry_count=-1,
        auto_close=0,
        enable_hls=0,
        enable_mp4=1,
        enable_rtsp=1,
        enable_rtmp=0,
        enable_ts=0,
        enable_fmp4=0,
        enable_audio=0,
        add_mute_audio=0,
        mp4_save_path="/recordings",
        mp4_max_second=SEGMENT_SECONDS,
    )
    if response.get("code") != 0:
        raise AssertionError(f"addStreamProxy failed: {response}")
    key = ((response.get("data") or {}).get("key"))
    if not key:
        raise AssertionError(f"missing proxy key: {response}")
    return str(key)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_duration(path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return float(completed.stdout.strip())


def decode_rtsp(url: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            url,
            "-t",
            "2",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def known_locations() -> dict[str, dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT l.id AS location_id, l.object_path, l.state,
                   s.id AS segment_id, s.stream, s.start_at, s.end_at, s.source
            FROM recording_locations l
            JOIN recording_segments s ON s.id = l.segment_id
            """
        ).fetchall()
    return {row["object_path"]: dict(row) for row in rows}


def infer_identity(path: Path) -> tuple[str, datetime] | None:
    parts = list(path.parts)
    try:
        app_index = parts.index("poc")
    except ValueError:
        return None
    if app_index + 2 >= len(parts):
        return None

    stream = parts[app_index + 1]
    date_dir = path.parent.name
    name = path.name.lstrip(".")
    if not name.endswith(".mp4"):
        return None

    prefix = name[:-4]
    pieces = prefix.split("-")
    # Current ZLM recorder filename:
    # YYYY-MM-DD-HH-MM-SS-index.mp4
    if len(pieces) < 7:
        return None
    try:
        dt = datetime(
            int(pieces[0]),
            int(pieces[1]),
            int(pieces[2]),
            int(pieces[3]),
            int(pieces[4]),
            int(pieces[5]),
            tzinfo=UTC,
        )
    except ValueError:
        return None

    if date_dir != dt.strftime("%Y-%m-%d"):
        return None
    return stream, dt


def persist_recovered(path: Path, stream: str, start: datetime, duration: float) -> bool:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT 1 FROM recording_locations WHERE object_path = ?",
            (str(path),),
        ).fetchone()
        if existing:
            conn.rollback()
            return False

        segment_id = str(uuid.uuid4())
        now = iso(datetime.now(UTC))
        end = start + timedelta(seconds=duration)
        conn.execute(
            """
            INSERT INTO recording_segments(
                id, camera_id, vhost, app, stream, start_at, end_at,
                duration_ms, size_bytes, source, created_at
            ) VALUES (?, ?, '__defaultVhost__', 'poc', ?, ?, ?, ?, ?, 'reconcile', ?)
            """,
            (
                segment_id,
                f"camera-{stream}",
                stream,
                iso(start),
                iso(end),
                round(duration * 1000),
                path.stat().st_size,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO recording_locations(
                id, segment_id, object_path, state,
                size_bytes, verified_at, created_at
            ) VALUES (?, ?, ?, 'AVAILABLE', ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                segment_id,
                str(path),
                path.stat().st_size,
                now,
                now,
            ),
        )
        conn.commit()
        return True


def mark_missing(location_id: str) -> bool:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state FROM recording_locations WHERE id = ?",
            (location_id,),
        ).fetchone()
        if not row or row["state"] == "MISSING":
            conn.rollback()
            return False
        conn.execute(
            "UPDATE recording_locations SET state='MISSING' WHERE id = ?",
            (location_id,),
        )
        conn.commit()
        return True


def record_run(entry: dict[str, Any]) -> None:
    existing = []
    if RUN_LOG.exists():
        existing = json.loads(RUN_LOG.read_text(encoding="utf-8"))
    existing.append(entry)
    RUN_LOG.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def reconcile(crash_after: int | None = None) -> dict[str, Any]:
    changes = 0
    recovered: list[str] = []
    missing: list[str] = []
    ambiguous: list[str] = []
    errors: list[dict[str, str]] = []

    def mutation_happened() -> None:
        nonlocal changes
        changes += 1
        if crash_after is not None and changes >= crash_after:
            marker = {
                "at": iso(time.time()),
                "changes_before_crash": changes,
            }
            (RUNTIME / "reconciliation-simulated-crash.json").write_text(
                json.dumps(marker, indent=2),
                encoding="utf-8",
            )
            raise SimulatedCrash(
                f"intentional reconciliation process crash after {changes} mutation(s)"
            )

    known = known_locations()

    # First preserve database truth and mark missing media. Never delete another
    # file just because a row is stale.
    for object_path, row in known.items():
        if row["state"] in {"DELETED", "MISSING"}:
            continue
        if not Path(object_path).exists():
            if mark_missing(row["location_id"]):
                missing.append(object_path)
                mutation_happened()

    known = known_locations()
    finalized = sorted(
        path
        for path in RECORDING_ROOT.rglob("*.mp4")
        if path.is_file() and not path.name.startswith(".")
    )

    for path in finalized:
        if str(path) in known:
            continue
        try:
            identity = infer_identity(path)
            if identity is None:
                ambiguous.append(str(path))
                continue
            stream, start = identity
            duration = ffprobe_duration(path)
            if duration <= 0:
                ambiguous.append(str(path))
                continue
            if persist_recovered(path, stream, start, duration):
                recovered.append(str(path))
                mutation_happened()
        except SimulatedCrash:
            raise
        except Exception as exc:
            errors.append({"path": str(path), "error": repr(exc)})

    result = {
        "at": iso(time.time()),
        "changes": changes,
        "recovered": recovered,
        "missing": missing,
        "ambiguous": ambiguous,
        "errors": errors,
    }
    record_run(result)
    return result


def prepare() -> None:
    version = wait_until(
        "ZLM API",
        lambda: (
            response if (response := zlm_api("version")).get("code") == 0 else None
        ),
        timeout=45,
    )
    key = add_proxy()
    wait_until("reconcile recorder active", recorder_active, timeout=45)
    baseline = wait_until(
        "three baseline segments",
        lambda: rows if len(rows := segments()) >= 3 else None,
        timeout=90,
    )

    # Deliberately lose one normal hook-indexing operation while acknowledging
    # success to ZLM.
    request_json(f"{API}/debug/drop-next-hook", method="POST")
    dropped_before = hook_summary()["dropped_hook_count"]
    dropped = wait_until(
        "one deliberately dropped hook",
        lambda: summary
        if (summary := hook_summary())["dropped_hook_count"] > dropped_before
        else None,
        timeout=30,
    )

    with connect() as conn:
        dropped_row = conn.execute(
            """
            SELECT object_path, received_at
            FROM poc_hook_events
            WHERE dropped = 1
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    if not dropped_row or not dropped_row["object_path"]:
        raise AssertionError("deliberately dropped hook has no object_path evidence")

    state = {
        "prepared_at": iso(time.time()),
        "proxy_key": key,
        "baseline_segment_count": len(baseline),
        "dropped_hook_summary": dropped,
        "dropped_hook": {
            "object_path": dropped_row["object_path"],
            "received_at": dropped_row["received_at"],
        },
        "zlm_version": version,
    }
    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(state, indent=2, ensure_ascii=False))


def hold_lock(seconds: float) -> None:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO poc_state(key, value)
            VALUES('db_lock_probe', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(time.time()),),
        )
        started = {
            "started_at": iso(time.time()),
            "seconds": seconds,
            "write_lock_acquired": True,
        }
        (RUNTIME / "db-lock-started.json").write_text(
            json.dumps(started, indent=2),
            encoding="utf-8",
        )
        time.sleep(seconds)
        conn.commit()
    finally:
        conn.close()

    (RUNTIME / "db-lock-finished.json").write_text(
        json.dumps({"finished_at": iso(time.time())}, indent=2),
        encoding="utf-8",
    )


def create_fixtures() -> None:
    rows = segments()
    if len(rows) < 3:
        raise AssertionError("not enough canonical segments for fault fixtures")

    guard = Path(rows[-1]["object_path"])
    stale = Path(rows[-2]["object_path"])
    source_for_orphan = Path(rows[-3]["object_path"])
    for path in (guard, stale, source_for_orphan):
        if not path.exists():
            raise AssertionError(f"fixture source missing: {path}")

    quarantine = RUNTIME / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    stale_saved = quarantine / stale.name
    shutil.move(stale, stale_saved)

    duration = ffprobe_duration(source_for_orphan)
    orphan_start = datetime.now(UTC) - timedelta(seconds=duration + 2)
    date_dir = orphan_start.strftime("%Y-%m-%d")
    proven_dir = RECORDING_ROOT / "record" / "poc" / STREAM / date_dir
    proven_dir.mkdir(parents=True, exist_ok=True)
    proven_name = orphan_start.strftime("%Y-%m-%d-%H-%M-%S") + "-999.mp4"
    proven = proven_dir / proven_name
    shutil.copy2(source_for_orphan, proven)

    ambiguous_dir = RECORDING_ROOT / "orphans"
    ambiguous_dir.mkdir(parents=True, exist_ok=True)
    ambiguous = ambiguous_dir / "mystery.mp4"
    shutil.copy2(source_for_orphan, ambiguous)

    fixture = {
        "created_at": iso(time.time()),
        "guard_path": str(guard),
        "guard_sha256": sha256(guard),
        "stale_catalog_path": str(stale),
        "stale_saved_copy": str(stale_saved),
        "proven_orphan_path": str(proven),
        "ambiguous_orphan_path": str(ambiguous),
    }
    (RUNTIME / "reconciliation-fixtures.json").write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(fixture, indent=2, ensure_ascii=False))


def verify() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    fixture = json.loads(
        (RUNTIME / "reconciliation-fixtures.json").read_text(encoding="utf-8")
    )

    final_run = reconcile()
    second_run = reconcile()

    if final_run["errors"] or second_run["errors"]:
        raise AssertionError(
            f"reconciliation errors: final={final_run} second={second_run}"
        )
    if second_run["changes"] != 0:
        raise AssertionError(
            f"reconciliation is not idempotent: {second_run}"
        )

    locations = known_locations()

    dropped_path = state["dropped_hook"]["object_path"]
    dropped_location = locations.get(dropped_path)
    if not dropped_location or dropped_location["state"] != "AVAILABLE":
        raise AssertionError(
            f"deliberately dropped-hook media was not recovered: {dropped_location}"
        )

    api_window_path = RUNTIME / "api-downtime.json"
    if not api_window_path.exists():
        raise AssertionError("API downtime window evidence missing")
    api_window = json.loads(api_window_path.read_text(encoding="utf-8"))
    api_start = parse_iso(api_window["started_at"])
    api_end = parse_iso(api_window["finished_at"])

    db_started_path = RUNTIME / "db-lock-started.json"
    db_finished_path = RUNTIME / "db-lock-finished.json"
    if not db_started_path.exists() or not db_finished_path.exists():
        raise AssertionError("SQLite lock-window evidence missing")
    db_started = json.loads(db_started_path.read_text(encoding="utf-8"))
    db_finished = json.loads(db_finished_path.read_text(encoding="utf-8"))
    db_start = parse_iso(db_started["started_at"])
    db_end = parse_iso(db_finished["finished_at"])

    def overlapping_available(start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = []
        for row in locations.values():
            if row["stream"] != STREAM or row["state"] != "AVAILABLE":
                continue
            seg_start = parse_iso(row["start_at"])
            seg_end = parse_iso(row["end_at"])
            if seg_start < end and seg_end > start:
                rows.append(row)
        return rows

    api_overlap = overlapping_available(api_start, api_end)
    if not api_overlap:
        raise AssertionError(
            "no AVAILABLE catalog media overlaps the FastAPI downtime window"
        )

    db_overlap = overlapping_available(db_start, db_end)
    if not db_overlap:
        raise AssertionError(
            "no AVAILABLE catalog media overlaps the SQLite lock window"
        )

    # FastAPI was completely stopped, so at least one finalized file from that
    # window should normally require reconciliation rather than hook insertion.
    # If a boundary lands exactly outside the window, still preserve the full
    # overlap list as evidence and require at least one reconcile-sourced row
    # within a small segment-duration margin.
    api_margin_start = api_start - timedelta(seconds=SEGMENT_SECONDS)
    api_margin_end = api_end + timedelta(seconds=SEGMENT_SECONDS)
    api_reconciled = [
        row
        for row in locations.values()
        if row["stream"] == STREAM
        and row["state"] == "AVAILABLE"
        and row["source"] == "reconcile"
        and parse_iso(row["start_at"]) < api_margin_end
        and parse_iso(row["end_at"]) > api_margin_start
    ]
    if not api_reconciled:
        raise AssertionError(
            "FastAPI downtime produced no nearby reconcile-sourced media"
        )

    stale = locations.get(fixture["stale_catalog_path"])
    if not stale or stale["state"] != "MISSING":
        raise AssertionError(
            f"stale catalog location was not marked MISSING: {stale}"
        )

    proven = locations.get(fixture["proven_orphan_path"])
    if not proven or proven["state"] != "AVAILABLE":
        raise AssertionError(
            f"proven orphan was not recovered: {proven}"
        )

    ambiguous = fixture["ambiguous_orphan_path"]
    if ambiguous in locations:
        raise AssertionError("ambiguous orphan was guessed into the catalog")
    if not Path(ambiguous).exists():
        raise AssertionError("ambiguous orphan media was deleted")

    guard = Path(fixture["guard_path"])
    if not guard.exists():
        raise AssertionError("valid guard media was deleted during reconciliation")
    if sha256(guard) != fixture["guard_sha256"]:
        raise AssertionError("valid guard media was modified during reconciliation")

    # Recovered proven orphan can be materialized into the normal ZLM VOD
    # namespace without guessing a different camera identity.
    VOD_ROOT.mkdir(parents=True, exist_ok=True)
    vod = VOD_ROOT / "recovered-orphan.mp4"
    shutil.copy2(Path(fixture["proven_orphan_path"]), vod)
    decode_rtsp("rtsp://zlm:554/record/recovered-orphan.mp4")

    active = recorder_active()
    if not active:
        raise AssertionError("local recorder is not active after fault recovery")

    all_runs = json.loads(RUN_LOG.read_text(encoding="utf-8")) if RUN_LOG.exists() else []
    summary = hook_summary()

    evidence = {
        "result": "PASS",
        "completed_at": iso(time.time()),
        "prepared": state,
        "fixtures": fixture,
        "reconciliation_runs": all_runs,
        "final_run": final_run,
        "idempotent_second_run": second_run,
        "catalog_checks": {
            "dropped_hook_path": dropped_path,
            "dropped_hook_recovered_state": dropped_location["state"],
            "api_downtime_available_overlap": api_overlap,
            "api_downtime_reconcile_sourced": api_reconciled,
            "db_lock_available_overlap": db_overlap,
            "stale_state": stale["state"],
            "proven_orphan_state": proven["state"],
            "ambiguous_cataloged": ambiguous in locations,
            "ambiguous_file_preserved": Path(ambiguous).exists(),
            "guard_preserved": guard.exists(),
            "guard_sha256_unchanged": sha256(guard) == fixture["guard_sha256"],
        },
        "hook_summary": summary,
        "recorder_active": active,
        "recovered_vod": {
            "path": str(vod),
            "rtsp_decode": "PASS",
        },
        "api_downtime": api_window,
        "db_lock_started": db_started,
        "db_lock_finished": db_finished,
        "simulated_worker_crash": json.loads(
            (RUNTIME / "reconciliation-simulated-crash.json").read_text(
                encoding="utf-8"
            )
        )
        if (RUNTIME / "reconciliation-simulated-crash.json").exists()
        else None,
    }

    try:
        zlm_api("delStreamProxy", key=state["proxy_key"])
    except Exception as exc:
        evidence["cleanup_warning"] = repr(exc)

    EVIDENCE.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    lock = sub.add_parser("hold-lock")
    lock.add_argument("--seconds", type=float, default=22)
    sub.add_parser("create-fixtures")
    rec = sub.add_parser("reconcile")
    rec.add_argument("--crash-after", type=int)
    sub.add_parser("verify")
    args = parser.parse_args()

    if args.command == "prepare":
        prepare()
    elif args.command == "hold-lock":
        hold_lock(args.seconds)
    elif args.command == "create-fixtures":
        create_fixtures()
    elif args.command == "reconcile":
        try:
            result = reconcile(args.crash_after)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except SimulatedCrash as exc:
            print(str(exc))
            raise SystemExit(42)
    else:
        verify()


if __name__ == "__main__":
    main()
