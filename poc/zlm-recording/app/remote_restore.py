from __future__ import annotations

import argparse
import json
import os
import shutil
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

STATE = Path("/runtime/remote-restore-state.json")
EVIDENCE = Path("/runtime/remote-restore-evidence.json")
STAGING = Path("/runtime/remote-staging")
CACHE = Path("/playback-cache")
STREAM = "remote-restore-poc"
SEGMENT_TARGET_SECONDS = 8
BWLIMIT = os.getenv("POC_RCLONE_BWLIMIT", "200k")
CACHE_MAX_BYTES = int(
    os.getenv("POC_PLAYBACK_CACHE_MAX_BYTES", "2200000")
)


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


def segments() -> list[dict[str, Any]]:
    items = request_json(f"{API}/debug/segments")["items"]
    return sorted(
        [item for item in items if item["stream"] == STREAM],
        key=lambda item: (item["start_at"], item["id"]),
    )


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
        mp4_max_second=SEGMENT_TARGET_SECONDS,
    )
    if response.get("code") != 0:
        raise AssertionError(f"addStreamProxy failed: {response}")
    key = ((response.get("data") or {}).get("key"))
    if not key:
        raise AssertionError(f"missing proxy key: {response}")
    return str(key)


def run_rclone(args: list[str], *, check: bool = True, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["rclone", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def wait_remote() -> None:
    wait_until(
        "rclone WebDAV remote",
        lambda: run_rclone(["lsd", "remote:"], check=False, timeout=10).returncode == 0,
        timeout=45,
    )


def rclone_version() -> str:
    return run_rclone(["version"], timeout=15).stdout.strip()


def ffprobe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,format_name",
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


def decode_rtsp(url: str, seconds: int = 2) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(
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
            str(seconds),
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "url": url,
        "decoded_seconds_requested": seconds,
        "wall_seconds": time.time() - started,
        "returncode": completed.returncode,
    }


def first_frame_rtsp(url: str) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            url,
            "-frames:v",
            "1",
            "-an",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "url": url,
        "first_frame_wall_seconds": time.perf_counter() - started,
        "returncode": completed.returncode,
    }


def cache_usage() -> dict[str, Any]:
    files = [
        path for path in CACHE.glob("*.mp4")
        if path.is_file()
    ]
    return {
        "bytes": sum(path.stat().st_size for path in files),
        "files": [
            {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
            }
            for path in sorted(files, key=lambda p: p.stat().st_mtime_ns)
        ],
    }


def enforce_cache_limit(limit_bytes: int) -> dict[str, Any]:
    before = cache_usage()
    evicted: list[str] = []

    files = sorted(
        [path for path in CACHE.glob("*.mp4") if path.is_file()],
        key=lambda path: path.stat().st_mtime_ns,
    )

    total = sum(path.stat().st_size for path in files)
    for path in files:
        if total <= limit_bytes:
            break
        size = path.stat().st_size
        path.unlink()
        total -= size
        evicted.append(str(path))

    after = cache_usage()
    if after["bytes"] > limit_bytes:
        raise AssertionError(
            f"cache limit enforcement failed: {after['bytes']} > {limit_bytes}"
        )

    return {
        "limit_bytes": limit_bytes,
        "before": before,
        "evicted": evicted,
        "after": after,
    }


def upload_remote(logical_name: str, source: Path) -> dict[str, Any]:
    STAGING.mkdir(parents=True, exist_ok=True)
    upload_copy = STAGING / logical_name
    shutil.copy2(source, upload_copy)
    remote = f"remote:archive/{logical_name}"
    run_rclone(["copyto", str(upload_copy), remote, "--retries", "2"], timeout=90)
    info = run_rclone(["lsjson", remote], timeout=30)
    upload_copy.unlink()
    return {
        "remote": remote,
        "source_segment_path": str(source),
        "source_size": source.stat().st_size,
        "lsjson": json.loads(info.stdout),
        "staging_removed": not upload_copy.exists(),
    }


def interrupted_restore(remote: str, final: Path) -> dict[str, Any]:
    overall_started = time.perf_counter()
    CACHE.mkdir(parents=True, exist_ok=True)
    final.unlink(missing_ok=True)
    partial = final.with_name(final.name + ".partial")
    partial.unlink(missing_ok=True)

    proc = subprocess.Popen(
        [
            "rclone",
            "copyto",
            remote,
            str(partial),
            "--bwlimit",
            BWLIMIT,
            "--retries",
            "1",
            "--low-level-retries",
            "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(1.5)
    proc.terminate()
    try:
        stdout, stderr = proc.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)

    if final.exists():
        raise AssertionError(
            "interrupted restore published final READY path before verification"
        )

    partial_exists = partial.exists()
    partial_size = partial.stat().st_size if partial_exists else 0

    # Retry to the same staging name. rclone may overwrite/restart the transfer;
    # either behavior is acceptable because the final path remains unpublished.
    retry_started = time.perf_counter()
    run_rclone(
        [
            "copyto",
            remote,
            str(partial),
            "--retries",
            "2",
            "--low-level-retries",
            "2",
        ],
        timeout=120,
    )
    retry_ready_seconds = time.perf_counter() - retry_started
    probe = ffprobe(partial)
    if float(probe["format"]["duration"]) <= 0:
        raise AssertionError(f"restored media is not playable: {probe}")

    os.replace(partial, final)
    return {
        "interrupted_returncode": proc.returncode,
        "interrupted_stdout": stdout[-1000:],
        "interrupted_stderr": stderr[-2000:],
        "partial_existed_after_interrupt": partial_exists,
        "partial_size_after_interrupt": partial_size,
        "final_existed_after_interrupt": False,
        "retry_probe": probe,
        "published_path": str(final),
        "published_size": final.stat().st_size,
        "retry_to_ready_seconds": retry_ready_seconds,
        "interrupted_attempt_plus_retry_seconds": time.perf_counter() - overall_started,
    }


def cache_ready_bytes() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    return sum(
        path.stat().st_size
        for path in CACHE.rglob("*")
        if path.is_file() and not path.name.endswith(".partial")
    )


def evict_to_limit(
    *,
    protected: set[Path],
    max_bytes: int,
) -> dict[str, Any]:
    before = cache_ready_bytes()
    candidates = sorted(
        (
            path
            for path in CACHE.rglob("*")
            if path.is_file()
            and not path.name.endswith(".partial")
            and path not in protected
        ),
        key=lambda path: path.stat().st_mtime_ns,
    )

    evicted: list[dict[str, Any]] = []
    current = before
    for path in candidates:
        if current <= max_bytes:
            break
        size = path.stat().st_size
        path.unlink()
        evicted.append({"path": str(path), "size_bytes": size})
        current -= size

    return {
        "configured_max_bytes": max_bytes,
        "before_bytes": before,
        "after_bytes": cache_ready_bytes(),
        "evicted": evicted,
    }


def prefetch(remote: str, final: Path) -> subprocess.Popen[str]:
    final.unlink(missing_ok=True)
    partial = final.with_name(final.name + ".partial")
    partial.unlink(missing_ok=True)
    return subprocess.Popen(
        [
            "rclone",
            "copyto",
            remote,
            str(partial),
            "--bwlimit",
            BWLIMIT,
            "--retries",
            "2",
            "--low-level-retries",
            "2",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def finish_prefetch(proc: subprocess.Popen[str], final: Path) -> dict[str, Any]:
    stdout, stderr = proc.communicate(timeout=120)
    if proc.returncode != 0:
        raise AssertionError(
            f"prefetch failed rc={proc.returncode}: {stderr[-2000:]}"
        )
    partial = final.with_name(final.name + ".partial")
    probe = ffprobe(partial)
    os.replace(partial, final)
    return {
        "returncode": proc.returncode,
        "stdout": stdout[-1000:],
        "stderr": stderr[-1000:],
        "probe": probe,
        "published_path": str(final),
    }


def prepare() -> None:
    wait_remote()
    proxy_key = add_proxy()
    wait_until("local recorder active", recorder_active, timeout=45)

    items = wait_until(
        "three local recording segments",
        lambda: rows if len(rows := segments()) >= 3 else None,
        timeout=90,
    )

    chosen = items[:3]
    for item in chosen:
        if not Path(item["object_path"]).exists():
            raise AssertionError(f"recording source missing: {item['object_path']}")

    uploads = [
        upload_remote("remote-1.mp4", Path(chosen[0]["object_path"])),
        upload_remote("remote-2.mp4", Path(chosen[1]["object_path"])),
    ]

    state = {
        "prepared_at": iso(time.time()),
        "proxy_key": proxy_key,
        "segment_count": len(items),
        "source_segments": chosen,
        "uploads": uploads,
        "rclone_version": rclone_version(),
    }
    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(state, indent=2, ensure_ascii=False))


def restore() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    uploads = state["uploads"]
    guard = Path(state["source_segments"][2]["object_path"])

    first = CACHE / "remote-1.mp4"
    second = CACHE / "remote-2.mp4"

    first_result = interrupted_restore(uploads[0]["remote"], first)

    # Start next-segment prefetch while the first restored segment is already
    # playable through ZLM. This exercises the desired playback/prefetch shape.
    prefetch_proc = prefetch(uploads[1]["remote"], second)
    time.sleep(0.5)
    first_frame = first_frame_rtsp(
        "rtsp://zlm:554/record/cache/remote-1.mp4"
    )
    first_play = decode_rtsp(
        "rtsp://zlm:554/record/cache/remote-1.mp4",
        seconds=2,
    )
    second_result = finish_prefetch(prefetch_proc, second)

    if not guard.exists():
        raise AssertionError("local canonical guard segment disappeared unexpectedly")
    if not first.exists() or not second.exists():
        raise AssertionError("both restored cache entries must be READY before eviction test")

    # Force a deterministic bounded-cache eviction: choose a limit that can
    # hold the larger single segment but not both together. This validates the
    # policy mechanics without depending on a universal production cache size.
    size_first = first.stat().st_size
    size_second = second.stat().st_size
    cache_limit = max(size_first, size_second) + 64 * 1024
    if cache_limit >= size_first + size_second:
        cache_limit = max(size_first, size_second)

    cache_eviction = enforce_cache_limit(cache_limit)
    if not cache_eviction["evicted"]:
        raise AssertionError("bounded cache test did not evict any entry")
    if not guard.exists():
        raise AssertionError("cache eviction deleted canonical local recording")
    if not cache_eviction["after"]["files"]:
        raise AssertionError("bounded cache evicted every restored segment unexpectedly")

    evidence = {
        "result": "RUNNING",
        "prepared": state,
        "restore": {
            "first_interrupted_and_retry": first_result,
            "first_frame_after_ready": first_frame,
            "first_vod_while_second_prefetching": first_play,
            "second_prefetch": second_result,
            "cache_eviction": {
                **cache_eviction,
                "canonical_guard_path": str(guard),
                "canonical_guard_exists_after": guard.exists(),
            },
        },
        "pre_failure_segment_count": len(segments()),
        "recorder_active_before_remote_failure": recorder_active(),
    }
    EVIDENCE.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False))


def failure_check() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    before = int(evidence["pre_failure_segment_count"])

    remote_attempt = run_rclone(
        ["lsf", "remote:archive"],
        check=False,
        timeout=15,
    )
    if remote_attempt.returncode == 0:
        raise AssertionError(
            "remote failure check expected WebDAV to be unavailable"
        )

    after = wait_until(
        "new local recording segment while remote is down",
        lambda: count if (count := len(segments())) > before else None,
        timeout=45,
    )
    active = recorder_active()
    if not active:
        raise AssertionError("local ZLM recorder stopped because remote was unavailable")

    evidence["remote_failure"] = {
        "remote_command_returncode": remote_attempt.returncode,
        "remote_stderr": remote_attempt.stderr[-2000:],
        "segment_count_before": before,
        "segment_count_after": after,
        "local_recording_continued": after > before,
        "recorder_active": active,
    }
    evidence["result"] = "PASS"
    evidence["completed_at"] = iso(time.time())

    try:
        zlm_api("delStreamProxy", key=evidence["prepared"]["proxy_key"])
    except Exception as exc:
        evidence["cleanup_warning"] = repr(exc)

    EVIDENCE.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "restore", "failure-check"])
    args = parser.parse_args()

    if args.command == "prepare":
        prepare()
    elif args.command == "restore":
        restore()
    else:
        failure_check()


if __name__ == "__main__":
    main()
