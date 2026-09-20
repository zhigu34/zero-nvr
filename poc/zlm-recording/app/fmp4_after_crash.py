from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen


RUNTIME = Path("/runtime")
VOD_ROOT = Path("/vod")
PRE = RUNTIME / "fmp4-precrash.json"
CRASH = RUNTIME / "fmp4-crash-inspection.json"
FINAL = RUNTIME / "fmp4-evidence.json"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


def decode_file(path_or_url: str, seconds: int = 3) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            path_or_url,
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


def read_rtsp_vod(name: str, seconds: int = 3) -> None:
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


def wait_http(url: str, timeout: int = 45) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last = exc
        time.sleep(1)
    raise RuntimeError(f"timeout waiting for {url}: {last!r}")


def inspect() -> None:
    pre = json.loads(PRE.read_text(encoding="utf-8"))
    partial = Path(pre["partial_path"])
    if not partial.exists():
        raise RuntimeError(f"interrupted file missing after SIGKILL: {partial}")
    if not partial.name.startswith("."):
        raise RuntimeError(
            f"expected ZLM in-progress hidden file, got {partial.name}"
        )

    partial_probe = ffprobe(str(partial))
    decode_file(str(partial), seconds=3)

    remux = RUNTIME / "fmp4-remux.mp4"
    subprocess.run(
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
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    remux_probe = ffprobe(str(remux))

    VOD_ROOT.mkdir(parents=True, exist_ok=True)
    interrupted_vod = VOD_ROOT / "interrupted.mp4"
    shutil.copy2(partial, interrupted_vod)

    evidence = {
        "inspected_at": now(),
        "partial_path": str(partial),
        "partial_size": partial.stat().st_size,
        "partial_probe": partial_probe,
        "partial_decode": "PASS",
        "remux_path": str(remux),
        "remux_probe": remux_probe,
        "interrupted_vod_path": str(interrupted_vod),
    }
    CRASH.write_text(
        json.dumps(evidence, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2))


def verify_vod() -> None:
    wait_http("http://zlm/index/api/version")

    pre = json.loads(PRE.read_text(encoding="utf-8"))
    crash = json.loads(CRASH.read_text(encoding="utf-8"))

    normal_http_probe = ffprobe("http://zlm/record/normal.mp4")
    interrupted_http_probe = ffprobe("http://zlm/record/interrupted.mp4")

    read_rtsp_vod("normal.mp4")
    read_rtsp_vod("interrupted.mp4")

    final = {
        "result": "PASS",
        "completed_at": now(),
        "precrash": pre,
        "crash_inspection": crash,
        "post_restart": {
            "normal_http_probe": normal_http_probe,
            "interrupted_http_probe": interrupted_http_probe,
            "normal_rtsp_vod": "PASS",
            "interrupted_rtsp_vod": "PASS",
        },
    }
    FINAL.write_text(
        json.dumps(final, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(final, indent=2))


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"inspect", "verify-vod"}:
        raise SystemExit("usage: fmp4_after_crash.py inspect|verify-vod")

    if sys.argv[1] == "inspect":
        inspect()
    else:
        verify_vod()


if __name__ == "__main__":
    main()
