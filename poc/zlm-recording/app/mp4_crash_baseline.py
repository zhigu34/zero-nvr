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
RECORDING_ROOT = Path("/recordings")
VOD_ROOT = Path("/vod")
STATE = Path("/runtime/mp4-baseline-state.json")
EVIDENCE = Path("/runtime/mp4-baseline-evidence.json")
STREAM = "mp4-baseline-crash"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def request_json(url: str, timeout: float = 10) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def zlm_api(name: str, **params: Any) -> dict[str, Any]:
    query = urlencode({"secret": ZLM_SECRET, **params})
    return request_json(f"{ZLM}/index/api/{name}?{query}")


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


def add_proxy() -> dict[str, Any]:
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
        mp4_max_second=60,
    )
    if response.get("code") != 0:
        raise RuntimeError(f"addStreamProxy failed: {response}")
    return response


def find_partial() -> Path | None:
    candidates = [
        path
        for path in RECORDING_ROOT.rglob(".*.mp4")
        if STREAM in path.parts and path.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def run_command(args: list[str], timeout: float = 60) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": True,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
            "wall_seconds": time.perf_counter() - started,
        }
    except subprocess.CalledProcessError as exc:
        return {
            "ok": False,
            "returncode": exc.returncode,
            "stdout": (exc.stdout or "")[-2000:],
            "stderr": (exc.stderr or "")[-2000:],
            "wall_seconds": time.perf_counter() - started,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": repr(exc),
            "wall_seconds": time.perf_counter() - started,
        }


def prepare() -> None:
    version = wait_until(
        "ZLM API",
        lambda: (
            response if (response := zlm_api("version")).get("code") == 0 else None
        ),
        timeout=45,
    )
    wait_until(
        "POC API",
        lambda: request_json(f"{API}/health").get("status") == "ok",
        timeout=30,
    )

    proxy = add_proxy()
    partial = wait_until(
        "open hidden ordinary MP4 file",
        lambda: (
            path
            if (path := find_partial()) is not None
            and path.stat().st_size > 32 * 1024
            else None
        ),
        timeout=45,
    )

    size_before = partial.stat().st_size
    time.sleep(6)
    size_after = partial.stat().st_size
    if size_after <= size_before:
        raise RuntimeError(
            f"in-progress ordinary MP4 did not grow: {size_before} -> {size_after}"
        )

    state = {
        "prepared_at": now(),
        "zlm_version": version,
        "proxy": proxy,
        "partial_path": str(partial),
        "partial_size_before": size_before,
        "partial_size_after": size_after,
    }
    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(state, indent=2, ensure_ascii=False))


def inspect() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    partial = Path(state["partial_path"])

    evidence: dict[str, Any] = {
        "result": "OBSERVATION",
        "inspected_at": now(),
        "prepared": state,
        "partial_exists_after_sigkill": partial.exists(),
    }

    if not partial.exists():
        evidence["recoverability"] = {
            "ffprobe": {"ok": False, "error": "file missing"},
            "decode": {"ok": False, "error": "file missing"},
            "remux": {"ok": False, "error": "file missing"},
        }
    else:
        evidence["partial_size_after_sigkill"] = partial.stat().st_size
        evidence["recoverability"] = {
            "ffprobe": run_command(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration,size,format_name",
                    "-of",
                    "json",
                    str(partial),
                ],
                timeout=30,
            ),
            "decode": run_command(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(partial),
                    "-t",
                    "3",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=30,
            ),
        }

        remux = Path("/runtime/mp4-baseline-remux.mp4")
        remux_result = run_command(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(partial),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(remux),
            ],
            timeout=60,
        )
        if remux_result.get("ok") and remux.exists():
            remux_result["output_path"] = str(remux)
            remux_result["output_size"] = remux.stat().st_size
        evidence["recoverability"]["remux"] = remux_result

        VOD_ROOT.mkdir(parents=True, exist_ok=True)
        vod = VOD_ROOT / "baseline-interrupted.mp4"
        shutil.copy2(partial, vod)
        evidence["vod_copy_path"] = str(vod)

    EVIDENCE.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False))


def verify_vod() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    vod = Path(evidence.get("vod_copy_path") or "")

    if not vod.is_file():
        vod_result = {
            "http_ffprobe": {"ok": False, "error": "no interrupted baseline file"},
            "rtsp_vod": {"ok": False, "error": "no interrupted baseline file"},
        }
    else:
        vod_result = {
            "http_ffprobe": run_command(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration,size,format_name",
                    "-of",
                    "json",
                    "http://zlm/record/baseline-interrupted.mp4",
                ],
                timeout=30,
            ),
            "rtsp_vod": run_command(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-rtsp_transport",
                    "tcp",
                    "-i",
                    "rtsp://zlm:554/record/baseline-interrupted.mp4",
                    "-t",
                    "3",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=30,
            ),
        }

    evidence["post_restart_vod"] = vod_result
    checks = [
        evidence["recoverability"].get("ffprobe", {}).get("ok", False),
        evidence["recoverability"].get("decode", {}).get("ok", False),
        evidence["recoverability"].get("remux", {}).get("ok", False),
        vod_result["http_ffprobe"].get("ok", False),
        vod_result["rtsp_vod"].get("ok", False),
    ]
    evidence["all_recovery_checks_passed"] = all(checks)
    evidence["completed_at"] = now()

    EVIDENCE.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "inspect", "verify-vod"])
    args = parser.parse_args()

    if args.command == "prepare":
        prepare()
    elif args.command == "inspect":
        inspect()
    else:
        verify_vod()


if __name__ == "__main__":
    main()
