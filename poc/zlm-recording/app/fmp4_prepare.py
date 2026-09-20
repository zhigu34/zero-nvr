from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


API = "http://127.0.0.1:8000"
ZLM = os.getenv("ZLM_BASE_URL", "http://zlm")
ZLM_SECRET = os.environ["ZLM_API_SECRET"]
RECORDING_ROOT = Path("/recordings")
VOD_ROOT = Path("/vod")
RUNTIME = Path("/runtime")
OUT = RUNTIME / "fmp4-precrash.json"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def get_json(url: str, timeout: float = 10) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def zlm_api(name: str, **params: Any) -> dict[str, Any]:
    query = urlencode({"secret": ZLM_SECRET, **params})
    return get_json(f"{ZLM}/index/api/{name}?{query}")


def wait_until(description: str, predicate, timeout: float, interval: float = 1):
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
    raise RuntimeError(f"timeout waiting for {description}; last={last!r}")


def add_proxy(stream: str, max_second: int) -> dict[str, Any]:
    response = zlm_api(
        "addStreamProxy",
        vhost="__defaultVhost__",
        app="poc",
        stream=stream,
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
        mp4_max_second=max_second,
    )
    if response.get("code") != 0:
        raise RuntimeError(f"addStreamProxy({stream}) failed: {response}")
    return response


def ffprobe(path_or_url: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,format_name",
            "-of",
            "json",
            path_or_url,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(completed.stdout)


def read_rtsp_vod(name: str, seconds: int = 2) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            f"rtsp://zlm:554/record/{name}",
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


def find_partial() -> Path | None:
    candidates = [
        p
        for p in RECORDING_ROOT.rglob(".*.mp4")
        if "fmp4-crash" in p.parts and p.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime_ns)


def main() -> None:
    VOD_ROOT.mkdir(parents=True, exist_ok=True)

    version = wait_until(
        "ZLM API",
        lambda: (
            response if (response := zlm_api("version")).get("code") == 0 else None
        ),
        timeout=45,
    )
    wait_until(
        "POC API",
        lambda: get_json(f"{API}/health").get("status") == "ok",
        timeout=30,
    )

    normal_proxy = add_proxy("fmp4-normal", max_second=8)

    def normal_segment():
        items = get_json(f"{API}/debug/segments")["items"]
        return next(
            (
                item
                for item in items
                if item["stream"] == "fmp4-normal"
                and item["source"] == "hook"
                and item["location_state"] == "AVAILABLE"
            ),
            None,
        )

    normal = wait_until(
        "one normally finalized fMP4 segment",
        normal_segment,
        timeout=60,
    )
    normal_path = Path(normal["object_path"])
    normal_probe = ffprobe(str(normal_path))

    normal_vod = VOD_ROOT / "normal.mp4"
    shutil.copy2(normal_path, normal_vod)

    # Exercise both the HTTP-file path and ZLM's MP4 RTSP VOD demuxer.
    normal_http_probe = ffprobe("http://zlm/record/normal.mp4")
    read_rtsp_vod("normal.mp4")

    crash_proxy = add_proxy("fmp4-crash", max_second=60)

    partial = wait_until(
        "open hidden fMP4 file",
        lambda: (
            p
            if (p := find_partial()) is not None and p.stat().st_size > 32 * 1024
            else None
        ),
        timeout=45,
    )

    size_before = partial.stat().st_size
    time.sleep(6)
    size_after = partial.stat().st_size
    if size_after <= size_before:
        raise RuntimeError(
            f"in-progress file did not grow: {size_before} -> {size_after}"
        )

    evidence = {
        "prepared_at": now(),
        "zlm_version": version,
        "normal_proxy": normal_proxy,
        "crash_proxy": crash_proxy,
        "normal_segment": normal,
        "normal_probe": normal_probe,
        "normal_http_probe": normal_http_probe,
        "normal_rtsp_vod": "PASS",
        "partial_path": str(partial),
        "partial_size_before": size_before,
        "partial_size_after": size_after,
    }
    OUT.write_text(
        json.dumps(evidence, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
