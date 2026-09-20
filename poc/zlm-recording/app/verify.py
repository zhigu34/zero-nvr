from __future__ import annotations

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
MEDIAMTX = os.getenv("MEDIAMTX_BASE_URL", "http://mediamtx:9998")
SEGMENT_SECONDS = int(os.getenv("POC_SEGMENT_SECONDS", "10"))
RUNTIME = Path("/runtime")
EVIDENCE_PATH = RUNTIME / "evidence.json"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(url, data=data, method=method, headers=headers)
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(url: str, timeout: float = 10) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8")


def zlm_api(name: str, **params: Any) -> dict[str, Any]:
    query = {"secret": ZLM_SECRET, **params}
    return request_json(f"{ZLM}/index/api/{name}?{urlencode(query)}")


def wait_until(description: str, predicate, timeout: float, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception as exc:
            last = repr(exc)
        time.sleep(interval)
    raise AssertionError(f"timeout waiting for {description}; last={last!r}")


def reader_count(path_name: str) -> int:
    metrics = get_text(f"{MEDIAMTX}/metrics")
    total = 0
    for line in metrics.splitlines():
        if not line.startswith("paths_readers{"):
            continue
        if f'name="{path_name}"' not in line:
            continue
        try:
            total += int(float(line.rsplit(" ", 1)[1]))
        except ValueError:
            pass
    return total


def ensure_proxy(stream: str, source_path: str, record: bool) -> dict[str, Any]:
    response = zlm_api(
        "addStreamProxy",
        vhost="__defaultVhost__",
        app="poc",
        stream=stream,
        url=f"rtsp://mediamtx:8554/{source_path}",
        rtp_type=0,
        retry_count=-1,
        auto_close=0,
        enable_hls=0,
        enable_mp4=1 if record else 0,
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
        raise AssertionError(f"addStreamProxy({stream}) failed: {response}")
    return response


def media_present(stream: str) -> dict[str, Any] | None:
    response = zlm_api(
        "getMediaList",
        schema="rtsp",
        vhost="__defaultVhost__",
        app="poc",
        stream=stream,
    )
    if response.get("code") != 0:
        return None
    return response if any(
        item.get("stream") == stream for item in (response.get("data") or [])
    ) else None


def start_zlm_downstream_reader(seconds: int = 12) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            "rtsp://zlm:554/poc/cam-main",
            "-t",
            str(seconds),
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def write_evidence(evidence: dict[str, Any]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def main() -> None:
    evidence: dict[str, Any] = {
        "started_at": now(),
        "result": "RUNNING",
        "segment_seconds": SEGMENT_SECONDS,
        "zlm_image": os.getenv("ZLM_IMAGE", "zlmediakit/zlmediakit:master"),
        "mediamtx_image": os.getenv(
            "MEDIAMTX_IMAGE", "bluenviron/mediamtx:1.21.0-ffmpeg"
        ),
        "checks": {},
    }

    try:
        wait_until(
            "POC API",
            lambda: request_json(f"{API}/health").get("status") == "ok",
            timeout=30,
        )

        zlm_version = wait_until(
            "ZLM API",
            lambda: (
                response
                if (response := zlm_api("version")).get("code") == 0
                else None
            ),
            timeout=45,
        )
        evidence["zlm_version"] = zlm_version

        wait_until(
            "MediaMTX metrics",
            lambda: "paths{" in get_text(f"{MEDIAMTX}/metrics"),
            timeout=45,
        )

        evidence["proxy_main"] = ensure_proxy("cam-main", "cam_main", record=True)
        evidence["proxy_sub"] = ensure_proxy("cam-sub", "cam_sub", record=False)

        wait_until("ZLM cam-main media", lambda: media_present("cam-main"), timeout=45)
        wait_until("ZLM cam-sub media", lambda: media_present("cam-sub"), timeout=45)

        baseline_summary = request_json(f"{API}/debug/summary")
        baseline_ffprobe_calls = baseline_summary["ffprobe_calls"]
        evidence["checks"]["baseline_summary_before_normal_phase"] = baseline_summary

        upstream_before = wait_until(
            "one upstream MediaMTX reader per source",
            lambda: (
                counts
                if (counts := {
                    "cam_main": reader_count("cam_main"),
                    "cam_sub": reader_count("cam_sub"),
                })
                == {"cam_main": 1, "cam_sub": 1}
                else None
            ),
            timeout=45,
        )
        evidence["checks"]["upstream_readers_before"] = upstream_before

        normal_segments = wait_until(
            "three finalized cam-main hook-indexed segments",
            lambda: (
                rows
                if len(
                    rows := [
                        item
                        for item in request_json(f"{API}/debug/segments")["items"]
                        if item["stream"] == "cam-main"
                        and item["source"] == "hook"
                    ]
                ) >= 3
                else None
            ),
            timeout=max(70, SEGMENT_SECONDS * 7),
        )
        normal_summary = request_json(f"{API}/debug/summary")
        evidence["checks"]["normal_cam_main_segments"] = normal_segments
        evidence["checks"]["normal_hook_summary"] = normal_summary

        if normal_summary["ffprobe_calls"] != baseline_ffprobe_calls:
            raise AssertionError(
                "normal hook path increased ffprobe call count; "
                f"baseline={baseline_ffprobe_calls} "
                f"after={normal_summary['ffprobe_calls']}"
            )

        request_json(f"{API}/debug/drop-next-hook", method="POST")
        dropped_before = normal_summary["dropped_hook_count"]

        dropped_summary = wait_until(
            "intentionally dropped hook",
            lambda: (
                summary
                if (summary := request_json(f"{API}/debug/summary"))[
                    "dropped_hook_count"
                ]
                > dropped_before
                else None
            ),
            timeout=max(45, SEGMENT_SECONDS * 4),
        )
        evidence["checks"]["dropped_hook_summary"] = dropped_summary

        first_reconcile = request_json(f"{API}/debug/reconcile", method="POST")
        evidence["checks"]["first_reconcile"] = first_reconcile
        if first_reconcile["recovered_count"] < 1:
            raise AssertionError(
                f"reconciliation recovered no file: {first_reconcile}"
            )
        if first_reconcile["errors"]:
            raise AssertionError(
                f"reconciliation returned errors: {first_reconcile['errors']}"
            )

        summary_after_reconcile = request_json(f"{API}/debug/summary")
        evidence["checks"]["summary_after_reconcile"] = summary_after_reconcile
        if summary_after_reconcile["ffprobe_calls"] <= baseline_ffprobe_calls:
            raise AssertionError(
                "lost-hook reconciliation did not increase ffprobe fallback count"
            )

        second_reconcile = request_json(f"{API}/debug/reconcile", method="POST")
        evidence["checks"]["second_reconcile"] = second_reconcile
        if second_reconcile["recovered_count"] != 0:
            raise AssertionError(
                f"second reconciliation was not idempotent: {second_reconcile}"
            )

        readers = [start_zlm_downstream_reader(), start_zlm_downstream_reader()]
        try:
            time.sleep(3)
            for idx, proc in enumerate(readers):
                if proc.poll() is not None:
                    stderr = proc.stderr.read() if proc.stderr else ""
                    raise AssertionError(
                        f"ZLM downstream reader {idx} exited early: {stderr}"
                    )

            upstream_with_downstream = {
                "cam_main": reader_count("cam_main"),
                "cam_sub": reader_count("cam_sub"),
            }
            evidence["checks"][
                "upstream_readers_with_two_zlm_viewers"
            ] = upstream_with_downstream
            if upstream_with_downstream != {"cam_main": 1, "cam_sub": 1}:
                raise AssertionError(
                    "downstream viewers increased source-facing reader count: "
                    f"{upstream_with_downstream}"
                )
        finally:
            for proc in readers:
                if proc.poll() is None:
                    proc.terminate()
            for proc in readers:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        segments = request_json(f"{API}/debug/segments")
        evidence["segments"] = segments["items"]

        if len(segments["items"]) != len(
            {item["object_path"] for item in segments["items"]}
        ):
            raise AssertionError("duplicate RecordingLocation object_path found")

        hook_durations = [
            item["duration_ms"]
            for item in segments["items"]
            if item["source"] == "hook" and item["stream"] == "cam-main"
        ]
        if not hook_durations:
            raise AssertionError("no hook-indexed duration evidence")
        evidence["checks"]["hook_durations_ms"] = hook_durations

        evidence["result"] = "PASS"
        evidence["completed_at"] = now()
        write_evidence(evidence)
        print(json.dumps(evidence, indent=2, ensure_ascii=False))
    except Exception as exc:
        evidence["result"] = "FAIL"
        evidence["completed_at"] = now()
        evidence["error"] = repr(exc)
        write_evidence(evidence)
        raise


if __name__ == "__main__":
    main()
