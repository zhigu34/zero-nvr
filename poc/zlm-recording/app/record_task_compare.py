from __future__ import annotations

import hashlib
import json
import os
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
VOD_PREFIX_IN_ZLM = "/opt/media/bin/www/record/"
VOD_ROOT = Path("/vod")
OUT = Path("/runtime/pre-roll-candidate-comparison.json")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def request_json(url: str, *, method: str = "GET", timeout: float = 10) -> dict[str, Any]:
    req = Request(url, method=method)
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def request_bytes(url: str, timeout: float = 15) -> bytes:
    with urlopen(url, timeout=timeout) as response:
        return response.read()


def zlm_api(name: str, **params: Any) -> dict[str, Any]:
    return request_json(
        f"{ZLM}/index/api/{name}?{urlencode({'secret': ZLM_SECRET, **params})}"
    )


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
    raise RuntimeError(f"timeout waiting for {description}; last={last!r}")


def add_proxy(stream: str) -> str:
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
        enable_mp4=0,
        enable_rtsp=1,
        enable_rtmp=0,
        enable_ts=0,
        enable_fmp4=0,
        enable_audio=0,
        add_mute_audio=0,
    )
    if response.get("code") != 0:
        raise RuntimeError(f"addStreamProxy failed: {response}")
    key = ((response.get("data") or {}).get("key"))
    if not key:
        raise RuntimeError(f"no proxy key: {response}")
    return str(key)


def del_proxy(key: str) -> None:
    try:
        zlm_api("delStreamProxy", key=key)
    except Exception:
        pass


def media_present(stream: str) -> bool:
    response = zlm_api(
        "getMediaList",
        schema="rtsp",
        vhost="__defaultVhost__",
        app="poc",
        stream=stream,
    )
    return response.get("code") == 0 and any(
        item.get("stream") == stream for item in (response.get("data") or [])
    )


def prime_frame_ring(stream: str) -> dict[str, Any]:
    url = f"rtsp://127.0.0.1/poc/{stream}?self=1"
    query = urlencode(
        {
            "secret": ZLM_SECRET,
            "url": url,
            "timeout_sec": 8,
            "expire_sec": 0,
            "async": 1,
        }
    )
    started = time.time()
    body = request_bytes(f"{ZLM}/index/api/getSnap?{query}", timeout=15)
    return {
        "requested_at": iso(started),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "note": "fast self-snapshot currently calls getFrameReader(), which creates the frame GOP Ring",
    }


def local_path_from_task_response(path: str) -> Path:
    if path.startswith(VOD_PREFIX_IN_ZLM):
        return VOD_ROOT / path[len(VOD_PREFIX_IN_ZLM):]
    raise RuntimeError(f"unexpected startRecordTask path: {path}")


def probe(path: Path) -> dict[str, Any]:
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


def first_frame_md5(path: Path) -> str:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "md5",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def run_start_record_task() -> dict[str, Any]:
    stream = "compare-task"
    key = add_proxy(stream)
    try:
        wait_until("compare-task stream", lambda: media_present(stream), 30)
        snap = prime_frame_ring(stream)
        time.sleep(15)

        runs: list[dict[str, Any]] = []
        for index in range(5):
            called_at = time.time()
            relative = f"compare-task/run-{index + 1}.mp4"
            response = zlm_api(
                "startRecordTask",
                vhost="__defaultVhost__",
                app="poc",
                stream=stream,
                path=relative,
                back_ms=10000,
                forward_ms=1000,
            )
            item: dict[str, Any] = {
                "index": index + 1,
                "called_at": iso(called_at),
                "response": response,
            }
            if response.get("code") == 0:
                returned = ((response.get("data") or {}).get("path"))
                if returned:
                    local = local_path_from_task_response(str(returned))
                    wait_until(
                        f"startRecordTask output {index + 1}",
                        lambda: local.exists() and local.stat().st_size > 0,
                        10,
                    )
                    time.sleep(1.5)
                    item["path"] = str(local)
                    item["probe"] = probe(local)
                    item["first_frame_md5"] = first_frame_md5(local)
            runs.append(item)
            time.sleep(3)

        durations = [
            float(item["probe"]["format"]["duration"])
            for item in runs
            if item.get("probe")
        ]
        md5s = [
            item["first_frame_md5"]
            for item in runs
            if item.get("first_frame_md5")
        ]
        return {
            "ring_prime": snap,
            "runs": runs,
            "duration_seconds": durations,
            "duration_min": min(durations) if durations else None,
            "duration_max": max(durations) if durations else None,
            "distinct_first_frame_md5": len(set(md5s)),
            "observation": (
                "Each API call is an independent task. Duration/first-frame data "
                "is evidence only; it is not treated as task extension."
            ),
        }
    finally:
        del_proxy(key)


def parse_iso(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def run_ordinary_start_record() -> dict[str, Any]:
    stream = "compare-normal"
    key = add_proxy(stream)
    try:
        wait_until("compare-normal stream", lambda: media_present(stream), 30)
        snap = prime_frame_ring(stream)
        time.sleep(15)

        trigger_at = time.time()
        response = zlm_api(
            "startRecord",
            type=1,
            vhost="__defaultVhost__",
            app="poc",
            stream=stream,
            customized_path="/recordings/compare-normal",
            max_second=60,
        )
        if response.get("code") != 0:
            raise RuntimeError(f"startRecord failed: {response}")

        time.sleep(5)
        stop_at = time.time()
        stop = zlm_api(
            "stopRecord",
            type=1,
            vhost="__defaultVhost__",
            app="poc",
            stream=stream,
        )
        if stop.get("code") != 0:
            raise RuntimeError(f"stopRecord failed: {stop}")

        def find_segment():
            items = request_json(f"{API}/debug/segments")["items"]
            return next(
                (
                    item
                    for item in reversed(items)
                    if item["stream"] == stream and item["source"] == "hook"
                ),
                None,
            )

        segment = wait_until("compare-normal hook segment", find_segment, 20)
        duration = segment["duration_ms"] / 1000.0
        hook_start = parse_iso(segment["start_at"])
        estimated_media_start_from_stop = stop_at - duration

        return {
            "ring_prime": snap,
            "trigger_at": iso(trigger_at),
            "stop_requested_at": iso(stop_at),
            "live_seconds_between_start_stop": stop_at - trigger_at,
            "segment": segment,
            "segment_duration_seconds": duration,
            "duration_minus_live_seconds": duration - (stop_at - trigger_at),
            "hook_start_minus_trigger_seconds": hook_start - trigger_at,
            "hook_start_minus_estimated_media_start_seconds": (
                hook_start - estimated_media_start_from_stop
            ),
            "observation": (
                "If segment duration materially exceeds the live start/stop interval, "
                "the normal recorder consumed GOP history. Compare hook start_at with "
                "the estimated historical media start to quantify absolute-time bias."
            ),
        }
    finally:
        del_proxy(key)


def main() -> None:
    evidence: dict[str, Any] = {
        "result": "OBSERVATION",
        "started_at": iso(time.time()),
        "startRecordTask": None,
        "ordinary_startRecord_with_ring": None,
    }

    try:
        evidence["startRecordTask"] = run_start_record_task()
    except Exception as exc:
        evidence["startRecordTask"] = {"error": repr(exc)}

    try:
        evidence["ordinary_startRecord_with_ring"] = run_ordinary_start_record()
    except Exception as exc:
        evidence["ordinary_startRecord_with_ring"] = {"error": repr(exc)}

    evidence["completed_at"] = iso(time.time())
    OUT.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
