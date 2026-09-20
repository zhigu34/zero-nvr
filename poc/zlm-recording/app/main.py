from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request


DB_PATH = Path(os.getenv("DB_PATH", "/runtime/poc.db"))
RECORDING_ROOT = Path(os.getenv("RECORDING_ROOT", "/recordings"))
HOOK_TOKEN = os.environ["ZLM_HOOK_TOKEN"]
POC_APP = os.getenv("POC_APP", "poc")
STREAM_CAMERA_MAP = {
    "cam-main": "camera-main",
    "cam-sub": "camera-sub",
}

app = FastAPI(title="zero-nvr ZLM POC evidence service")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recording_segments (
                id TEXT PRIMARY KEY,
                camera_id TEXT NOT NULL,
                vhost TEXT NOT NULL,
                app TEXT NOT NULL,
                stream TEXT NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recording_locations (
                id TEXT PRIMARY KEY,
                segment_id TEXT NOT NULL REFERENCES recording_segments(id),
                object_path TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                verified_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS poc_hook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                object_path TEXT,
                dropped INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS poc_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO poc_state(key, value) VALUES('drop_next_hook', '0')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO poc_state(key, value) VALUES('ffprobe_calls', '0')"
        )


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def parse_hook_payload(raw: bytes, content_type: str) -> dict[str, Any]:
    if "application/json" in content_type:
        return json.loads(raw.decode("utf-8"))

    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def stream_to_camera(stream: str) -> str:
    return STREAM_CAMERA_MAP.get(stream, f"camera-{stream}")


def create_segment_from_hook(conn: sqlite3.Connection, payload: dict[str, Any]) -> bool:
    object_path = str(payload["file_path"])

    existing = conn.execute(
        "SELECT 1 FROM recording_locations WHERE object_path = ?",
        (object_path,),
    ).fetchone()
    if existing:
        return False

    start_epoch = float(payload["start_time"])
    duration_s = float(payload["time_len"])
    start_dt = datetime.fromtimestamp(start_epoch, tz=UTC)
    end_dt = start_dt + timedelta(seconds=duration_s)

    segment_id = str(uuid.uuid4())
    now = utc_now()
    conn.execute(
        """
        INSERT INTO recording_segments(
            id, camera_id, vhost, app, stream, start_at, end_at,
            duration_ms, size_bytes, source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            segment_id,
            stream_to_camera(str(payload["stream"])),
            str(payload.get("vhost", "__defaultVhost__")),
            str(payload["app"]),
            str(payload["stream"]),
            iso_utc(start_dt),
            iso_utc(end_dt),
            round(duration_s * 1000),
            int(payload["file_size"]),
            "hook",
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO recording_locations(
            id, segment_id, object_path, state, size_bytes, verified_at, created_at
        ) VALUES (?, ?, ?, 'AVAILABLE', ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            segment_id,
            object_path,
            int(payload["file_size"]),
            now,
            now,
        ),
    )
    return True


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "time": utc_now()}


@app.post("/internal/hooks/zlm/record-mp4")
async def zlm_record_mp4(request: Request, token: str) -> dict[str, Any]:
    if not secrets.compare_digest(token, HOOK_TOKEN):
        raise HTTPException(status_code=403, detail="invalid hook token")

    raw = await request.body()
    payload = parse_hook_payload(raw, request.headers.get("content-type", ""))
    object_path = str(payload.get("file_path", ""))

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        drop_row = conn.execute(
            "SELECT value FROM poc_state WHERE key = 'drop_next_hook'"
        ).fetchone()
        drop = bool(drop_row and drop_row["value"] == "1")

        if drop:
            conn.execute(
                "UPDATE poc_state SET value = '0' WHERE key = 'drop_next_hook'"
            )

        conn.execute(
            """
            INSERT INTO poc_hook_events(received_at, object_path, dropped, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                utc_now(),
                object_path,
                1 if drop else 0,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )

        if not drop:
            create_segment_from_hook(conn, payload)

        conn.commit()

    return {"code": 0, "msg": "success"}


@app.post("/debug/drop-next-hook")
def drop_next_hook() -> dict[str, Any]:
    with connect() as conn:
        conn.execute(
            "UPDATE poc_state SET value = '1' WHERE key = 'drop_next_hook'"
        )
    return {"drop_next_hook": True}


def ffprobe(path: Path) -> dict[str, Any]:
    with connect() as conn:
        conn.execute(
            """
            UPDATE poc_state
            SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
            WHERE key = 'ffprobe_calls'
            """
        )

    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:format_tags=creation_time",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(completed.stdout)


CURRENT_ZLM_NAME = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})-(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})(?:-\d+)?\.mp4$"
)
LEGACY_ZLM_NAME = re.compile(
    r"(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})(?:-\d+)?\.mp4$"
)
DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_time_from_path(path: Path) -> datetime | None:
    match = CURRENT_ZLM_NAME.match(path.name)
    if match:
        return datetime.fromisoformat(
            f"{match.group('date')}T{match.group('h')}:{match.group('m')}:{match.group('s')}+00:00"
        )

    match = LEGACY_ZLM_NAME.match(path.name)
    if match and DATE_DIR.match(path.parent.name):
        return datetime.fromisoformat(
            f"{path.parent.name}T{match.group('h')}:{match.group('m')}:{match.group('s')}+00:00"
        )

    return None


def infer_stream(path: Path) -> str:
    parts = set(path.parts)
    for stream in STREAM_CAMERA_MAP:
        if stream in parts:
            return stream
    return "cam-main"


def recover_file(conn: sqlite3.Connection, path: Path) -> bool:
    object_path = str(path)
    existing = conn.execute(
        "SELECT 1 FROM recording_locations WHERE object_path = ?",
        (object_path,),
    ).fetchone()
    if existing:
        return False

    probe = ffprobe(path)
    format_info = probe.get("format", {})
    duration_s = float(format_info.get("duration") or 0)
    if duration_s <= 0:
        raise RuntimeError(f"ffprobe returned invalid duration for {path}")

    start_dt = parse_time_from_path(path)
    if start_dt is None:
        creation_time = (format_info.get("tags") or {}).get("creation_time")
        if creation_time:
            start_dt = datetime.fromisoformat(creation_time.replace("Z", "+00:00"))

    if start_dt is None:
        start_dt = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC) - timedelta(
            seconds=duration_s
        )

    stream = infer_stream(path)
    end_dt = start_dt + timedelta(seconds=duration_s)
    size_bytes = path.stat().st_size
    now = utc_now()
    segment_id = str(uuid.uuid4())

    conn.execute(
        """
        INSERT INTO recording_segments(
            id, camera_id, vhost, app, stream, start_at, end_at,
            duration_ms, size_bytes, source, created_at
        ) VALUES (?, ?, '__defaultVhost__', ?, ?, ?, ?, ?, ?, 'reconcile', ?)
        """,
        (
            segment_id,
            stream_to_camera(stream),
            POC_APP,
            stream,
            iso_utc(start_dt),
            iso_utc(end_dt),
            round(duration_s * 1000),
            size_bytes,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO recording_locations(
            id, segment_id, object_path, state, size_bytes, verified_at, created_at
        ) VALUES (?, ?, ?, 'AVAILABLE', ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            segment_id,
            object_path,
            size_bytes,
            now,
            now,
        ),
    )
    return True


@app.post("/debug/reconcile")
def reconcile() -> dict[str, Any]:
    recovered: list[str] = []
    errors: list[dict[str, str]] = []

    RECORDING_ROOT.mkdir(parents=True, exist_ok=True)
    paths = sorted(
        p for p in RECORDING_ROOT.rglob("*.mp4") if not p.name.startswith(".")
    )

    with connect() as conn:
        for path in paths:
            existing = conn.execute(
                "SELECT 1 FROM recording_locations WHERE object_path = ?",
                (str(path),),
            ).fetchone()
            if existing:
                continue

            try:
                conn.execute("BEGIN IMMEDIATE")
                if recover_file(conn, path):
                    recovered.append(str(path))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                errors.append({"path": str(path), "error": str(exc)})

    return {
        "scanned_files": len(paths),
        "recovered": recovered,
        "recovered_count": len(recovered),
        "errors": errors,
    }


@app.get("/debug/segments")
def segments() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*, l.object_path, l.state AS location_state
            FROM recording_segments s
            JOIN recording_locations l ON l.segment_id = s.id
            ORDER BY s.start_at, s.id
            """
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/debug/summary")
def summary() -> dict[str, Any]:
    with connect() as conn:
        segment_count = conn.execute(
            "SELECT COUNT(*) AS n FROM recording_segments"
        ).fetchone()["n"]
        hook_segment_count = conn.execute(
            "SELECT COUNT(*) AS n FROM recording_segments WHERE source = 'hook'"
        ).fetchone()["n"]
        reconciled_segment_count = conn.execute(
            "SELECT COUNT(*) AS n FROM recording_segments WHERE source = 'reconcile'"
        ).fetchone()["n"]
        location_count = conn.execute(
            "SELECT COUNT(*) AS n FROM recording_locations"
        ).fetchone()["n"]
        hook_count = conn.execute(
            "SELECT COUNT(*) AS n FROM poc_hook_events"
        ).fetchone()["n"]
        dropped_hook_count = conn.execute(
            "SELECT COUNT(*) AS n FROM poc_hook_events WHERE dropped = 1"
        ).fetchone()["n"]
        ffprobe_calls = int(
            conn.execute(
                "SELECT value FROM poc_state WHERE key = 'ffprobe_calls'"
            ).fetchone()["value"]
        )

    return {
        "segment_count": segment_count,
        "hook_segment_count": hook_segment_count,
        "reconciled_segment_count": reconciled_segment_count,
        "location_count": location_count,
        "hook_count": hook_count,
        "dropped_hook_count": dropped_hook_count,
        "ffprobe_calls": ffprobe_calls,
    }
