from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "http://127.0.0.1:8000"
ZLM = os.getenv("ZLM_BASE_URL", "http://zlm")
ZLM_SECRET = os.environ["ZLM_API_SECRET"]

DB_PATH = Path(os.getenv("DB_PATH", "/runtime/poc.db"))
PREBUFFER_ROOT = Path("/prebuffer")
OUTPUT_ROOT = Path("/runtime/event-recovery-persistent")
STATE = Path("/runtime/event-preroll-recovery-state.json")
EVIDENCE = Path("/runtime/event-preroll-recovery.json")

STREAM = "event-recovery"
SEGMENT_SECONDS = int(os.getenv("POC_PREBUFFER_SEGMENT_SECONDS", "5"))
PRE_ROLL_SECONDS = int(os.getenv("POC_PRE_ROLL_SECONDS", "10"))
POST_ROLL_SECONDS = int(os.getenv("POC_POST_ROLL_SECONDS", "10"))
TOLERANCE_SECONDS = 1.25

CURRENT_ZLM_NAME = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})-(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})(?:-\d+)?\.mp4$"
)
LEGACY_ZLM_NAME = re.compile(
    r"(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})(?:-\d+)?\.mp4$"
)
DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


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
        mp4_save_path="/prebuffer",
        mp4_max_second=SEGMENT_SECONDS,
    )
    if response.get("code") != 0:
        raise AssertionError(f"addStreamProxy failed: {response}")
    key = ((response.get("data") or {}).get("key"))
    if not key:
        raise AssertionError(f"missing proxy key: {response}")
    return str(key)


def parse_start(path: Path) -> float:
    match = CURRENT_ZLM_NAME.match(path.name)
    if match:
        return datetime.fromisoformat(
            f"{match.group('date')}T{match.group('h')}:{match.group('m')}:{match.group('s')}+00:00"
        ).timestamp()

    match = LEGACY_ZLM_NAME.match(path.name)
    if match and DATE_DIR.match(path.parent.name):
        return datetime.fromisoformat(
            f"{path.parent.name}T{match.group('h')}:{match.group('m')}:{match.group('s')}+00:00"
        ).timestamp()

    raise AssertionError(f"cannot derive finalized fragment start from path: {path}")


def probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name:format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    data = json.loads(completed.stdout)
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    duration = float(fmt.get("duration") or 0)
    if duration <= 0:
        raise AssertionError(f"invalid finalized prebuffer duration: {path}")
    return {
        "duration": duration,
        "codec_name": streams[0].get("codec_name") if streams else None,
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
    }


def scan_filesystem() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(PREBUFFER_ROOT.rglob("*.mp4")):
        if path.name.startswith(".") or STREAM not in path.parts or not path.is_file():
            continue
        media = probe(path)
        start = parse_start(path)
        items.append(
            {
                "path": str(path),
                "start": start,
                "end": start + media["duration"],
                "duration": media["duration"],
                "codec_name": media["codec_name"],
                "size_bytes": media["size_bytes"],
            }
        )
    return items


def hook_known_paths() -> set[str]:
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT payload_json FROM poc_hook_events WHERE dropped = 0"
        ).fetchall()
    finally:
        conn.close()

    paths: set[str] = set()
    for row in rows:
        payload = json.loads(row["payload_json"])
        if payload.get("stream") == STREAM and payload.get("file_path"):
            paths.add(str(payload["file_path"]))
    return paths


def merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged: list[list[float]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        current = merged[-1]
        if start <= current[1] + TOLERANCE_SECONDS:
            current[1] = max(current[1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def copy_publish(fragment: dict[str, Any]) -> dict[str, Any]:
    source = Path(fragment["path"])
    relative = source.relative_to(PREBUFFER_ROOT)
    final = OUTPUT_ROOT / relative
    partial = final.with_name(final.name + ".partial")
    final.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(source, partial)
    if partial.stat().st_size != source.stat().st_size:
        raise AssertionError(f"recovery copy size mismatch: {source}")

    verified = probe(partial)
    with partial.open("rb+") as handle:
        os.fsync(handle.fileno())
    os.replace(partial, final)

    return {
        **fragment,
        "published_path": str(final),
        "verified_duration": verified["duration"],
        "verified_codec": verified["codec_name"],
    }


def prepare() -> None:
    wait_until(
        "POC API",
        lambda: request_json(f"{API}/health").get("status") == "ok",
        timeout=30,
    )
    proxy_key = add_proxy()
    wait_until("rolling prebuffer recorder active", recorder_active, timeout=45)

    warm = wait_until(
        "three finalized prebuffer files",
        lambda: files if len(files := scan_filesystem()) >= 3 else None,
        timeout=max(75, SEGMENT_SECONDS * 12),
    )

    event_time = time.time()
    state = {
        "prepared_at": iso(event_time),
        "proxy_key": proxy_key,
        "trigger": {
            "event_at": event_time,
            "event_at_iso": iso(event_time),
            "required_start": event_time - PRE_ROLL_SECONDS,
            "required_start_at": iso(event_time - PRE_ROLL_SECONDS),
            "required_end": event_time + POST_ROLL_SECONDS,
            "required_end_at": iso(event_time + POST_ROLL_SECONDS),
        },
        "warm_files": warm,
    }
    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(state, indent=2, ensure_ascii=False))


def recover() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    trigger = state["trigger"]

    wait_until(
        "POC API after restart",
        lambda: request_json(f"{API}/health").get("status") == "ok",
        timeout=30,
    )
    if not recorder_active():
        raise AssertionError("ZLM prebuffer recorder stopped during FastAPI restart")

    # Give the fragment containing required_end time to finalize normally.
    wait_until(
        "filesystem coverage through trigger post-roll",
        lambda: (
            files
            if any(item["end"] >= trigger["required_end"] for item in (files := scan_filesystem()))
            else None
        ),
        timeout=max(45, SEGMENT_SECONDS * 8),
    )

    files = scan_filesystem()
    selected = [
        item
        for item in files
        if item["start"] < trigger["required_end"]
        and item["end"] > trigger["required_start"]
    ]
    if not selected:
        raise AssertionError("filesystem recovery found no trigger-overlapping fragments")

    published = [copy_publish(item) for item in selected]
    coverage = merge([(item["start"], item["end"]) for item in published])

    covering = next(
        (
            (start, end)
            for start, end in coverage
            if start <= trigger["required_start"] + TOLERANCE_SECONDS
            and end >= trigger["required_end"] - TOLERANCE_SECONDS
        ),
        None,
    )
    if not covering:
        raise AssertionError(
            f"filesystem-only recovery did not cover trigger window: {coverage}"
        )

    known = hook_known_paths()
    filesystem_only = [
        item for item in published if item["path"] not in known
    ]

    evidence = {
        "result": "PASS",
        "completed_at": iso(time.time()),
        "prepared": state,
        "recorder_active_after_api_restart": True,
        "filesystem_scan_count": len(files),
        "selected_from_filesystem": selected,
        "published": published,
        "merged_published_coverage": [
            {"start_at": iso(start), "end_at": iso(end)}
            for start, end in coverage
        ],
        "target_coverage": {
            "start_at": trigger["required_start_at"],
            "end_at": trigger["required_end_at"],
        },
        "hook_known_selected_paths": sorted(
            item["path"] for item in published if item["path"] in known
        ),
        "filesystem_only_promoted": filesystem_only,
        "note": (
            "Selection and promotion were derived from persisted trigger JSON + "
            "tmpfs filesystem scan. poc_hook_events were read only after promotion "
            "to report whether any selected fragments had no successful hook record."
        ),
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
    parser.add_argument("command", choices=["prepare", "recover"])
    args = parser.parse_args()

    if args.command == "prepare":
        prepare()
    else:
        recover()


if __name__ == "__main__":
    main()
