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
PERSISTENT_ROOT = Path("/runtime/event-recordings")

SEGMENT_SECONDS = int(os.getenv("POC_PREBUFFER_SEGMENT_SECONDS", "5"))
PRE_ROLL_SECONDS = int(os.getenv("POC_PRE_ROLL_SECONDS", "10"))
POST_ROLL_SECONDS = int(os.getenv("POC_POST_ROLL_SECONDS", "10"))
BUFFER_SECONDS = int(os.getenv("POC_BUFFER_SECONDS", "35"))
PREBUFFER_LIMIT_BYTES = int(
    os.getenv("POC_PREBUFFER_TMPFS_BYTES", "268435456")
)

# Trigger clusters exercise both overlap/extension and idle-buffer recovery.
# The full run is intentionally long enough to cross many fragment boundaries.
TRIGGER_OFFSETS = [0.7, 3.2, 7.6, 30.4, 33.1, 58.7, 62.3, 66.9, 89.5, 94.2]

CURRENT_ZLM_NAME = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})-(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})(?:-\d+)?\.mp4$"
)
LEGACY_ZLM_NAME = re.compile(
    r"(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})(?:-\d+)?\.mp4$"
)
DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utc_iso(ts: float) -> str:
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


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def hook_fragments(stream: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, received_at, object_path, payload_json
            FROM poc_hook_events
            WHERE dropped = 0
            ORDER BY id
            """
        ).fetchall()

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        payload = json.loads(row["payload_json"])
        if payload.get("stream") != stream:
            continue
        path = str(payload.get("file_path", ""))
        if not path.startswith("/prebuffer/") or path in seen:
            continue
        seen.add(path)

        start = float(payload["start_time"])
        duration = float(payload["time_len"])
        out.append(
            {
                "hook_id": row["id"],
                "hook_received_at": row["received_at"],
                "path": path,
                "start": start,
                "end": start + duration,
                "duration": duration,
                "size": int(payload["file_size"]),
            }
        )
    return out


def recorder_active(stream: str) -> bool:
    response = zlm_api(
        "isRecording",
        type=1,
        vhost="__defaultVhost__",
        app="poc",
        stream=stream,
    )
    return response.get("code") == 0 and bool(response.get("status"))


def add_proxy(stream: str, source: str) -> str:
    response = zlm_api(
        "addStreamProxy",
        vhost="__defaultVhost__",
        app="poc",
        stream=stream,
        url=f"rtsp://mediamtx:8554/{source}",
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
        raise AssertionError(f"addStreamProxy did not return proxy key: {response}")
    return str(key)


def delete_proxy(key: str) -> None:
    response = zlm_api("delStreamProxy", key=key)
    if response.get("code") != 0:
        raise AssertionError(f"delStreamProxy failed: {response}")


def merge_windows(windows: list[tuple[float, float]], tolerance: float = 0.0) -> list[tuple[float, float]]:
    if not windows:
        return []
    ordered = sorted(windows)
    merged: list[list[float]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        current = merged[-1]
        if start <= current[1] + tolerance:
            current[1] = max(current[1], end)
        else:
            merged.append([start, end])
    return [(item[0], item[1]) for item in merged]


def overlaps(fragment: dict[str, Any], window: tuple[float, float]) -> bool:
    return fragment["start"] < window[1] and fragment["end"] > window[0]


def ffprobe_media(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name:format=duration",
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
    duration = float((data.get("format") or {}).get("duration") or 0)
    streams = data.get("streams") or []
    codec = streams[0].get("codec_name") if streams else None
    return {"duration": duration, "codec_name": codec}


def promote(
    label: str,
    fragment: dict[str, Any],
    promoted: dict[str, dict[str, Any]],
) -> None:
    src = Path(fragment["path"])
    if not src.exists():
        raise AssertionError(f"finalized prebuffer file disappeared before promotion: {src}")

    try:
        relative = src.relative_to(PREBUFFER_ROOT)
    except ValueError:
        relative = Path(src.name)

    final = PERSISTENT_ROOT / label / relative
    partial = final.with_name(final.name + ".partial")
    final.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(src, partial)
    if partial.stat().st_size != src.stat().st_size:
        partial.unlink(missing_ok=True)
        raise AssertionError(f"promotion size mismatch for {src}")

    media = ffprobe_media(partial)
    duration = media["duration"]
    if duration <= 0:
        partial.unlink(missing_ok=True)
        raise AssertionError(f"promoted media has invalid duration: {src}")

    # Publish only after the copy is fully written and inspected.
    with partial.open("rb+") as handle:
        os.fsync(handle.fileno())
    os.replace(partial, final)

    promoted[str(src)] = {
        **fragment,
        "persistent_path": str(final),
        "verified_duration": duration,
        "verified_codec": media["codec_name"],
        "promoted_at": time.time(),
    }


def current_tmpfs_bytes() -> int:
    return sum(
        path.stat().st_size
        for path in PREBUFFER_ROOT.rglob("*")
        if path.is_file()
    )


def tmpfs_capacity() -> dict[str, int]:
    stat = os.statvfs(PREBUFFER_ROOT)
    return {
        "total_bytes": stat.f_blocks * stat.f_frsize,
        "free_bytes": stat.f_bavail * stat.f_frsize,
    }


def gc_ephemeral(
    stream: str,
    now_ts: float,
    windows: list[tuple[float, float]],
    promoted: dict[str, dict[str, Any]],
) -> list[str]:
    removed: list[str] = []
    cutoff = now_ts - BUFFER_SECONDS

    for fragment in hook_fragments(stream):
        if fragment["end"] >= cutoff:
            continue

        path = fragment["path"]
        # Promotion runs before GC. A file that a known Event still needs must
        # either already be safely promoted or remain in tmpfs.
        needed = any(overlaps(fragment, window) for window in windows)
        if needed and path not in promoted:
            continue

        file_path = Path(path)
        if file_path.exists():
            file_path.unlink()
            removed.append(path)
    return removed


def parse_time_from_path(path: Path) -> float | None:
    match = CURRENT_ZLM_NAME.match(path.name)
    if match:
        dt = datetime.fromisoformat(
            f"{match.group('date')}T{match.group('h')}:{match.group('m')}:{match.group('s')}+00:00"
        )
        return dt.timestamp()

    match = LEGACY_ZLM_NAME.match(path.name)
    if match and DATE_DIR.match(path.parent.name):
        dt = datetime.fromisoformat(
            f"{path.parent.name}T{match.group('h')}:{match.group('m')}:{match.group('s')}+00:00"
        )
        return dt.timestamp()
    return None


def filesystem_reconstruction_sample(stream: str) -> dict[str, Any]:
    files = [
        path
        for path in PREBUFFER_ROOT.rglob("*.mp4")
        if stream in path.parts and path.is_file() and not path.name.startswith(".")
    ]
    items: list[dict[str, Any]] = []
    for path in sorted(files)[-8:]:
        media = ffprobe_media(path)
        duration = media["duration"]
        start = parse_time_from_path(path)
        items.append(
            {
                "path": str(path),
                "duration": duration,
                "codec_name": media["codec_name"],
                "start_from_path": utc_iso(start) if start is not None else None,
                "size": path.stat().st_size,
            }
        )
    return {"visible_finalized_files": len(files), "sample": items}


def coverage_for_event(
    event_time: float,
    promoted: dict[str, dict[str, Any]],
    tolerance: float = 1.25,
) -> dict[str, Any]:
    target = (event_time - PRE_ROLL_SECONDS, event_time + POST_ROLL_SECONDS)
    intervals = merge_windows(
        [(item["start"], item["end"]) for item in promoted.values()],
        tolerance=tolerance,
    )

    for start, end in intervals:
        if start <= target[0] + tolerance and end >= target[1] - tolerance:
            return {
                "ok": True,
                "target_start": utc_iso(target[0]),
                "target_end": utc_iso(target[1]),
                "coverage_start": utc_iso(start),
                "coverage_end": utc_iso(end),
                "extra_before_seconds": max(0.0, target[0] - start),
                "extra_after_seconds": max(0.0, end - target[1]),
            }

    return {
        "ok": False,
        "target_start": utc_iso(target[0]),
        "target_end": utc_iso(target[1]),
        "merged_coverage": [
            {"start": utc_iso(start), "end": utc_iso(end)}
            for start, end in intervals
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stream", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--gop-seconds", type=float, required=True)
    args = parser.parse_args()

    output = Path(f"/runtime/event-preroll-{args.label}.json")
    proxy_key: str | None = None
    promoted: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    gc_removed: list[str] = []
    max_tmpfs_bytes = 0
    recorder_false_samples = 0

    zlm_version = zlm_api("version")
    evidence: dict[str, Any] = {
        "result": "RUNNING",
        "zlm_version": zlm_version,
        "stream": args.stream,
        "source": args.source,
        "label": args.label,
        "gop_seconds": args.gop_seconds,
        "segment_target_seconds": SEGMENT_SECONDS,
        "pre_roll_seconds": PRE_ROLL_SECONDS,
        "post_roll_seconds": POST_ROLL_SECONDS,
        "buffer_seconds": BUFFER_SECONDS,
        "trigger_offsets": TRIGGER_OFFSETS,
        "started_at": utc_iso(time.time()),
    }

    try:
        proxy_key = add_proxy(args.stream, args.source)
        wait_until(
            "ZLM rolling recorder active",
            lambda: recorder_active(args.stream),
            timeout=45,
        )

        # Warm the buffer until several ordinary on_record_mp4 fragments exist.
        warm = wait_until(
            "at least four finalized prebuffer fragments",
            lambda: (
                items
                if len(items := hook_fragments(args.stream)) >= 4
                else None
            ),
            timeout=max(75, SEGMENT_SECONDS * 12),
        )
        evidence["warmup_fragments"] = warm
        capacity = tmpfs_capacity()
        evidence["tmpfs_capacity"] = capacity
        evidence["configured_tmpfs_limit_bytes"] = PREBUFFER_LIMIT_BYTES
        if capacity["total_bytes"] > int(PREBUFFER_LIMIT_BYTES * 1.05):
            raise AssertionError(
                "prebuffer filesystem is not bounded to the configured tmpfs size: "
                f"{capacity['total_bytes']} > {PREBUFFER_LIMIT_BYTES}"
            )

        test_epoch = time.time()
        next_trigger = 0

        final_deadline = test_epoch + TRIGGER_OFFSETS[-1] + POST_ROLL_SECONDS
        hard_deadline = final_deadline + max(30, SEGMENT_SECONDS * 6)

        while time.time() < hard_deadline:
            now_ts = time.time()

            while (
                next_trigger < len(TRIGGER_OFFSETS)
                and now_ts >= test_epoch + TRIGGER_OFFSETS[next_trigger]
            ):
                event_time = time.time()
                events.append(
                    {
                        "id": f"E{next_trigger + 1}",
                        "occurred_at": event_time,
                        "occurred_at_iso": utc_iso(event_time),
                        "required_start": event_time - PRE_ROLL_SECONDS,
                        "required_end": event_time + POST_ROLL_SECONDS,
                    }
                )
                next_trigger += 1

            windows = merge_windows(
                [
                    (event["required_start"], event["required_end"])
                    for event in events
                ]
            )

            fragments = hook_fragments(args.stream)
            for fragment in fragments:
                if fragment["path"] in promoted:
                    continue
                if any(overlaps(fragment, window) for window in windows):
                    promote(args.label, fragment, promoted)

            gc_removed.extend(
                gc_ephemeral(
                    args.stream,
                    now_ts,
                    windows,
                    promoted,
                )
            )

            max_tmpfs_bytes = max(max_tmpfs_bytes, current_tmpfs_bytes())
            if not recorder_active(args.stream):
                recorder_false_samples += 1

            if next_trigger == len(TRIGGER_OFFSETS) and now_ts >= final_deadline:
                checks = [
                    coverage_for_event(event["occurred_at"], promoted)
                    for event in events
                ]
                if all(check["ok"] for check in checks):
                    # Require at least one additional fragment boundary after
                    # final required coverage while recorder is still active.
                    latest_end = max(item["end"] for item in promoted.values())
                    if latest_end >= final_deadline:
                        break

            time.sleep(0.5)
        else:
            raise AssertionError("event pre-roll test reached hard deadline")

        coverage_checks = [
            coverage_for_event(event["occurred_at"], promoted)
            for event in events
        ]
        if len(events) != len(TRIGGER_OFFSETS):
            raise AssertionError(
                f"expected {len(TRIGGER_OFFSETS)} events, got {len(events)}"
            )
        if not all(check["ok"] for check in coverage_checks):
            raise AssertionError(f"coverage failure: {coverage_checks}")
        if recorder_false_samples:
            raise AssertionError(
                f"rolling recorder was inactive in {recorder_false_samples} samples"
            )

        if len(promoted) != len({item["persistent_path"] for item in promoted.values()}):
            raise AssertionError("duplicate persistent promotion path detected")

        multi_event_fragments = []
        for item in promoted.values():
            overlap_ids = [
                event["id"]
                for event in events
                if item["start"] < event["required_end"]
                and item["end"] > event["required_start"]
            ]
            if len(overlap_ids) > 1:
                multi_event_fragments.append(
                    {"path": item["path"], "event_ids": overlap_ids}
                )
        if not multi_event_fragments:
            raise AssertionError(
                "no promoted fragment overlapped multiple Events; "
                "POC-04 deduplication was not exercised"
            )

        if max_tmpfs_bytes > PREBUFFER_LIMIT_BYTES:
            raise AssertionError(
                f"tmpfs usage exceeded configured bound: "
                f"{max_tmpfs_bytes} > {PREBUFFER_LIMIT_BYTES}"
            )

        verified_codecs = sorted(
            {
                item.get("verified_codec")
                for item in promoted.values()
                if item.get("verified_codec")
            }
        )
        if args.label == "h265" and verified_codecs != ["hevc"]:
            raise AssertionError(
                f"H.265 test did not produce HEVC media: {verified_codecs}"
            )

        # Ephemeral fragments must not have become canonical recording rows in
        # the normal POC catalog merely because they existed in tmpfs.
        canonical = request_json(f"{API}/debug/segments")["items"]
        bad = [item for item in canonical if item["stream"] == args.stream]
        if bad:
            raise AssertionError(
                f"ephemeral prebuffer fragments were indexed as canonical: {bad}"
            )

        reconstruction = filesystem_reconstruction_sample(args.stream)
        if reconstruction["visible_finalized_files"] < 1:
            raise AssertionError(
                "no finalized tmpfs file remained for filesystem reconstruction"
            )

        fragment_durations = [
            item["duration"] for item in hook_fragments(args.stream)
        ]
        evidence.update(
            {
                "result": "PASS",
                "completed_at": utc_iso(time.time()),
                "events": events,
                "merged_required_windows": [
                    {"start": utc_iso(start), "end": utc_iso(end)}
                    for start, end in merge_windows(
                        [
                            (event["required_start"], event["required_end"])
                            for event in events
                        ]
                    )
                ],
                "coverage_checks": coverage_checks,
                "promoted_count": len(promoted),
                "promoted": list(promoted.values()),
                "multi_event_fragments": multi_event_fragments,
                "gc_removed_count": len(set(gc_removed)),
                "max_tmpfs_bytes": max_tmpfs_bytes,
                "fragment_duration_seconds": fragment_durations,
                "verified_codecs": verified_codecs,
                "fragment_duration_min": min(fragment_durations),
                "fragment_duration_max": max(fragment_durations),
                "recorder_active_after_events": recorder_active(args.stream),
                "filesystem_reconstruction": reconstruction,
            }
        )

        if not evidence["recorder_active_after_events"]:
            raise AssertionError("rolling recorder stopped after final Event")

        output.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps(evidence, indent=2, ensure_ascii=False))
    except Exception as exc:
        evidence["result"] = "FAIL"
        evidence["completed_at"] = utc_iso(time.time())
        evidence["error"] = repr(exc)
        evidence["events"] = events
        evidence["promoted"] = list(promoted.values())
        evidence["max_tmpfs_bytes"] = max_tmpfs_bytes
        output.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        raise
    finally:
        if proxy_key:
            try:
                delete_proxy(proxy_key)
            except Exception:
                pass


if __name__ == "__main__":
    main()
