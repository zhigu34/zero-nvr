from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "http://127.0.0.1:8000"
ZLM = os.getenv("ZLM_BASE_URL", "http://zlm")
ZLM_SECRET = os.environ["ZLM_API_SECRET"]
STATE = Path("/runtime/api-restart-state.json")
EVIDENCE = Path("/runtime/api-restart-evidence.json")
STREAM = "api-restart-poc"
SEGMENT_SECONDS = 6


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


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
        mp4_max_second=SEGMENT_SECONDS,
    )
    if response.get("code") != 0:
        raise AssertionError(f"addStreamProxy failed: {response}")
    key = ((response.get("data") or {}).get("key"))
    if not key:
        raise AssertionError(f"missing proxy key: {response}")
    return str(key)


def prepare() -> None:
    wait_until(
        "POC API",
        lambda: request_json(f"{API}/health").get("status") == "ok",
        timeout=30,
    )
    version = wait_until(
        "ZLM API",
        lambda: (
            response if (response := zlm_api("version")).get("code") == 0 else None
        ),
        timeout=45,
    )

    proxy_key = add_proxy()
    wait_until("ZLM recorder active", recorder_active, timeout=45)
    initial = wait_until(
        "two hook-indexed segments before API restart",
        lambda: rows if len(rows := segments()) >= 2 else None,
        timeout=60,
    )

    state = {
        "prepared_at": iso(time.time()),
        "zlm_version": version,
        "proxy_key": proxy_key,
        "initial_segments": initial,
        "initial_segment_count": len(initial),
    }
    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(state, indent=2, ensure_ascii=False))


def verify(downtime_start: float, downtime_end: float) -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))

    wait_until(
        "POC API after restart",
        lambda: request_json(f"{API}/health").get("status") == "ok",
        timeout=30,
    )

    if not recorder_active():
        raise AssertionError(
            "ZLM recorder is not active after FastAPI restart; "
            "control-plane downtime must not deliberately stop recording"
        )

    pre_reconcile = segments()
    reconcile = request_json(f"{API}/debug/reconcile", method="POST")
    if reconcile["errors"]:
        raise AssertionError(f"reconciliation errors after API restart: {reconcile}")

    post_reconcile = segments()
    overlapping = []
    for item in post_reconcile:
        start = parse_iso(item["start_at"])
        end = parse_iso(item["end_at"])
        if start < downtime_end and end > downtime_start:
            overlapping.append(item)

    if not overlapping:
        raise AssertionError(
            "no finalized recording segment overlaps the FastAPI downtime window"
        )

    reconciled_overlap = [
        item for item in overlapping if item["source"] == "reconcile"
    ]
    delayed_or_retried_hook_overlap = [
        item
        for item in overlapping
        if item["source"] == "hook"
        and parse_iso(item["created_at"]) >= downtime_end
    ]

    if not reconciled_overlap and not delayed_or_retried_hook_overlap:
        raise AssertionError(
            "downtime media exists, but the test did not prove post-restart "
            "catalog convergence through either reconciliation or delayed/retried hook delivery"
        )

    if len(post_reconcile) <= int(state["initial_segment_count"]):
        raise AssertionError(
            "recording catalog did not grow after API restart/reconciliation"
        )

    second = request_json(f"{API}/debug/reconcile", method="POST")
    if second["errors"] or second["recovered_count"] != 0:
        raise AssertionError(
            f"post-restart reconciliation is not idempotent: {second}"
        )

    evidence = {
        "result": "PASS",
        "completed_at": iso(time.time()),
        "downtime": {
            "start_at": iso(downtime_start),
            "end_at": iso(downtime_end),
            "duration_seconds": downtime_end - downtime_start,
        },
        "prepared": state,
        "recorder_active_after_restart": True,
        "segments_before_reconcile": pre_reconcile,
        "first_reconcile": reconcile,
        "segments_after_reconcile": post_reconcile,
        "segments_overlapping_downtime": overlapping,
        "reconciled_overlap": reconciled_overlap,
        "delayed_or_retried_hook_overlap": delayed_or_retried_hook_overlap,
        "catalog_convergence_mechanism": (
            "reconciliation"
            if reconciled_overlap
            else "zlm_hook_retry_or_delayed_delivery"
        ),
        "second_reconcile": second,
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
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--downtime-start", type=float, required=True)
    verify_parser.add_argument("--downtime-end", type=float, required=True)
    args = parser.parse_args()

    if args.command == "prepare":
        prepare()
    else:
        verify(args.downtime_start, args.downtime_end)


if __name__ == "__main__":
    main()
