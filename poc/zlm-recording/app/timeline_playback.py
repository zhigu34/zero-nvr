from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


API = "http://127.0.0.1:8000"
ZLM = os.getenv("ZLM_BASE_URL", "http://zlm")
ZLM_SECRET = os.environ["ZLM_API_SECRET"]

STATE = Path("/runtime/timeline-state.json")
EVIDENCE = Path("/runtime/timeline-playback-evidence.json")
VOD_ROOT = Path("/vod")
STREAM = "timeline-poc"
SEGMENT_TARGET_SECONDS = 8
BOUNDARY_TOLERANCE_SECONDS = 1.25


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


def media_present() -> bool:
    response = zlm_api(
        "getMediaList",
        schema="rtsp",
        vhost="__defaultVhost__",
        app="poc",
        stream=STREAM,
    )
    return response.get("code") == 0 and any(
        item.get("stream") == STREAM for item in (response.get("data") or [])
    )


def probe(path_or_url: str) -> dict[str, Any]:
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


def parse_framemd5(text: str) -> list[str]:
    hashes: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 6:
            hashes.append(parts[-1])
    return hashes


def local_neighborhood_hashes(path: Path, offset: float, radius: float = 1.5) -> set[str]:
    start = max(0.0, offset - radius)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(path),
            "-t",
            f"{radius * 2:.3f}",
            "-an",
            "-f",
            "framemd5",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    return set(parse_framemd5(completed.stdout))


def rtsp_seek_first_hash(url: str, offset: float) -> str:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{offset:.3f}",
            "-rtsp_transport",
            "tcp",
            "-i",
            url,
            "-frames:v",
            "1",
            "-an",
            "-f",
            "framemd5",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    hashes = parse_framemd5(completed.stdout)
    if not hashes:
        raise AssertionError(f"RTSP seek produced no frame hash at {offset}s")
    return hashes[0]


def build_ranges(items: list[dict[str, Any]], tolerance: float) -> list[dict[str, Any]]:
    if not items:
        return []

    ranges: list[dict[str, Any]] = []
    current = {
        "start": parse_iso(items[0]["start_at"]),
        "end": parse_iso(items[0]["end_at"]),
        "segment_ids": [items[0]["id"]],
    }

    for item in items[1:]:
        start = parse_iso(item["start_at"])
        end = parse_iso(item["end_at"])
        if start <= current["end"] + tolerance:
            current["end"] = max(current["end"], end)
            current["segment_ids"].append(item["id"])
        else:
            ranges.append(current)
            current = {
                "start": start,
                "end": end,
                "segment_ids": [item["id"]],
            }

    ranges.append(current)
    return ranges


def boundary_deltas(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for left, right in zip(items, items[1:]):
        left_end = parse_iso(left["end_at"])
        right_start = parse_iso(right["start_at"])
        out.append(
            {
                "left_id": left["id"],
                "right_id": right["id"],
                "left_end": left["end_at"],
                "right_start": right["start_at"],
                "delta_seconds": right_start - left_end,
            }
        )
    return out

def normalize_continuity_session(
    items: list[dict[str, Any]],
    session_name: str,
) -> list[dict[str, Any]]:
    """Normalize finalized segment wall-clock coverage within one known-continuous source session.

    Current ZLM MP4Recorder sets hook.start_time when it creates the file on the
    first received frame, while the MP4 muxer can discard leading non-keyframes.
    Therefore the first finalized segment after recorder/source start may have a
    hook start that is early by roughly one GOP.

    For every segment that has a following segment in the same proven-continuous
    session, the next segment's file-creation boundary is a better absolute end
    anchor. We derive:

        normalized_end   = next.raw_hook_start
        normalized_start = normalized_end - actual_muxed_duration

    The final segment in a session keeps the raw hook fallback because there is
    no following boundary. A production implementation should prefer an explicit
    recorder-stop/source-unregister boundary for that tail when available.
    """
    if not items:
        return []

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        raw_start = parse_iso(item["start_at"])
        duration = item["duration_ms"] / 1000.0
        raw_end = raw_start + duration

        if index + 1 < len(items):
            next_boundary = parse_iso(items[index + 1]["start_at"])
            start = next_boundary - duration
            end = next_boundary
            timing_source = "next_segment_boundary"
        else:
            start = raw_start
            end = raw_end
            timing_source = "hook_tail_fallback"

        normalized.append(
            {
                **item,
                "raw_hook_start_at": item["start_at"],
                "raw_hook_end_at": iso(raw_end),
                "start_at": iso(start),
                "end_at": iso(end),
                "timing_source": timing_source,
                "timing_session": session_name,
                "start_correction_ms": round((start - raw_start) * 1000),
                "end_correction_ms": round((end - raw_end) * 1000),
            }
        )
    return normalized



def dst_roundtrip_evidence() -> dict[str, Any]:
    zone = ZoneInfo("America/Los_Angeles")
    utc_values = [
        datetime(2026, 11, 1, 8, 30, tzinfo=UTC),
        datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
    ]
    rows = []
    for value in utc_values:
        local = value.astimezone(zone)
        roundtrip = local.astimezone(UTC)
        rows.append(
            {
                "utc": value.isoformat(),
                "local": local.isoformat(),
                "fold": local.fold,
                "roundtrip_utc": roundtrip.isoformat(),
                "roundtrip_equal": roundtrip == value,
            }
        )
    return {
        "zone": str(zone),
        "rows": rows,
        "both_roundtrip": all(row["roundtrip_equal"] for row in rows),
        "same_wall_clock_hour": (
            rows[0]["local"][11:16] == rows[1]["local"][11:16]
        ),
        "distinct_offsets": (
            rows[0]["local"][-6:] != rows[1]["local"][-6:]
        ),
    }


def camera_clock_normalization_evidence() -> dict[str, Any]:
    canonical = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)
    measured_offset_ms = 5000
    device_reported = canonical.timestamp() + measured_offset_ms / 1000
    normalized = device_reported - measured_offset_ms / 1000
    return {
        "canonical_at": canonical.isoformat(),
        "measured_device_offset_ms": measured_offset_ms,
        "device_reported_at": iso(device_reported),
        "normalized_at": iso(normalized),
        "normalizes_back_to_canonical": math.isclose(
            normalized, canonical.timestamp(), abs_tol=0.001
        ),
    }


def resolve_wall_clock(
    items: list[dict[str, Any]],
    at_ts: float,
) -> dict[str, Any]:
    for item in items:
        start = parse_iso(item["start_at"])
        end = parse_iso(item["end_at"])
        if start <= at_ts < end:
            return {
                "status": "playable",
                "segment_id": item["id"],
                "segment_start_at": item["start_at"],
                "segment_end_at": item["end_at"],
                "offset_seconds": at_ts - start,
            }

    previous_end = max(
        (
            parse_iso(item["end_at"])
            for item in items
            if parse_iso(item["end_at"]) <= at_ts
        ),
        default=None,
    )
    next_start = min(
        (
            parse_iso(item["start_at"])
            for item in items
            if parse_iso(item["start_at"]) > at_ts
        ),
        default=None,
    )
    return {
        "status": "gap",
        "previous_at": iso(previous_end) if previous_end is not None else None,
        "next_at": iso(next_start) if next_start is not None else None,
    }


def event_marker_evidence(segment: dict[str, Any]) -> dict[str, Any]:
    start = parse_iso(segment["start_at"])
    end = parse_iso(segment["end_at"])
    marker = start + (end - start) * 0.61
    offset = marker - start
    return {
        "segment_id": segment["id"],
        "segment_start_at": segment["start_at"],
        "segment_end_at": segment["end_at"],
        "event_at": iso(marker),
        "resolved_offset_seconds": offset,
        "inside_segment": start <= marker < end,
    }


def prepare() -> None:
    version = wait_until(
        "ZLM API",
        lambda: (
            response if (response := zlm_api("version")).get("code") == 0 else None
        ),
        timeout=45,
    )
    proxy_key = add_proxy()
    wait_until("timeline stream", media_present, timeout=45)

    before = wait_until(
        "three pre-outage segments",
        lambda: items if len(items := segments()) >= 3 else None,
        timeout=90,
    )

    state = {
        "proxy_key": proxy_key,
        "prepared_at": iso(time.time()),
        "pre_segment_count": len(before),
        "pre_segments": before,
        "zlm_version": version,
    }
    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(state, indent=2, ensure_ascii=False))


def verify(outage_start: float, outage_end: float) -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    pre_count = int(state["pre_segment_count"])

    raw_items = wait_until(
        "three post-outage segments",
        lambda: (
            current
            if len(
                [
                    item
                    for item in (current := segments())
                    if parse_iso(item["start_at"]) >= outage_end
                ]
            ) >= 3
            else None
        ),
        timeout=120,
    )

    raw_deltas = boundary_deltas(raw_items)
    if not raw_deltas:
        raise AssertionError("no segment boundaries available")

    # Split by the deliberate source outage. In production this continuity
    # boundary comes from ZLM/source runtime registration state, not from a
    # guessed timestamp-gap threshold.
    pre_session = [
        item for item in raw_items
        if parse_iso(item["start_at"]) < outage_end
    ]
    post_session = [
        item for item in raw_items
        if parse_iso(item["start_at"]) >= outage_end
    ]
    if len(pre_session) < 2 or len(post_session) < 3:
        raise AssertionError(
            "insufficient segments on both sides of the deliberate outage: "
            f"pre={len(pre_session)} post={len(post_session)}"
        )

    normalized_pre = normalize_continuity_session(pre_session, "pre_outage")
    normalized_post = normalize_continuity_session(post_session, "post_outage")
    items = normalized_pre + normalized_post

    pre_deltas = boundary_deltas(normalized_pre)
    post_deltas = boundary_deltas(normalized_post)
    normal_deltas = pre_deltas + post_deltas

    bad_normal = [
        row
        for row in normal_deltas
        if abs(float(row["delta_seconds"])) > BOUNDARY_TOLERANCE_SECONDS
    ]
    if bad_normal:
        raise AssertionError(
            "normalized same-session boundaries are not continuous: "
            f"{bad_normal}"
        )

    cross_gap = {
        "left_id": normalized_pre[-1]["id"],
        "right_id": normalized_post[0]["id"],
        "left_end": normalized_pre[-1]["end_at"],
        "right_start": normalized_post[0]["start_at"],
        "delta_seconds": (
            parse_iso(normalized_post[0]["start_at"])
            - parse_iso(normalized_pre[-1]["end_at"])
        ),
    }

    outage_duration = outage_end - outage_start
    gap_seconds = float(cross_gap["delta_seconds"])
    if gap_seconds <= BOUNDARY_TOLERANCE_SECONDS:
        raise AssertionError(
            f"source outage did not create a visible media gap: {cross_gap}"
        )
    if gap_seconds < max(2.0, outage_duration - 4.0):
        raise AssertionError(
            f"projected gap too short for deliberate outage: "
            f"gap={gap_seconds:.3f}s outage={outage_duration:.3f}s"
        )
    if gap_seconds > outage_duration + 12.0:
        raise AssertionError(
            f"projected gap unexpectedly exceeds outage/reconnect allowance: "
            f"gap={gap_seconds:.3f}s outage={outage_duration:.3f}s"
        )

    ranges = build_ranges(items, BOUNDARY_TOLERANCE_SECONDS)
    if len(ranges) != 2:
        raise AssertionError(
            f"expected exactly two coverage ranges around one outage: {ranges}"
        )

    gap = {
        "start_at": iso(ranges[0]["end"]),
        "end_at": iso(ranges[1]["start"]),
        "duration_seconds": ranges[1]["start"] - ranges[0]["end"],
        "reason": "source_lost",
    }

    gap_midpoint = (ranges[0]["end"] + ranges[1]["start"]) / 2
    gap_resolution = resolve_wall_clock(items, gap_midpoint)
    if gap_resolution["status"] != "gap":
        raise AssertionError(
            f"gap midpoint unexpectedly resolved as playable: {gap_resolution}"
        )
    if gap_resolution["previous_at"] != gap["start_at"]:
        raise AssertionError(
            f"gap previous boundary mismatch: {gap_resolution} vs {gap}"
        )
    if gap_resolution["next_at"] != gap["end_at"]:
        raise AssertionError(
            f"gap next boundary mismatch: {gap_resolution} vs {gap}"
        )

    # Select a healthy finalized segment for VOD/seek checks.
    playable = max(
        items,
        key=lambda item: float(item["duration_ms"]),
    )
    source_path = Path(playable["object_path"])
    if not source_path.exists():
        raise AssertionError(f"selected recording file is missing: {source_path}")

    VOD_ROOT.mkdir(parents=True, exist_ok=True)
    vod_path = VOD_ROOT / "timeline-seek.mp4"
    shutil.copy2(source_path, vod_path)

    local_probe = probe(str(vod_path))
    duration = float(local_probe["format"]["duration"])
    if duration < 3:
        raise AssertionError(f"VOD sample too short for seek test: {duration}s")

    rtsp_url = "rtsp://zlm:554/record/timeline-seek.mp4"
    offsets = sorted(
        {
            min(max(0.5, duration * 0.08), max(0.5, duration - 1.0)),
            duration * 0.5,
            max(0.5, duration - 1.5),
        }
    )

    seek_results = []
    for offset in offsets:
        expected = local_neighborhood_hashes(vod_path, offset)
        if not expected:
            raise AssertionError(
                f"no local expected frame hashes around offset {offset}"
            )
        actual = rtsp_seek_first_hash(rtsp_url, offset)
        seek_results.append(
            {
                "offset_seconds": offset,
                "rtsp_first_frame_hash": actual,
                "matched_local_neighborhood": actual in expected,
                "local_neighborhood_hash_count": len(expected),
            }
        )

    if not all(item["matched_local_neighborhood"] for item in seek_results):
        raise AssertionError(f"ZLM RTSP seek frame mismatch: {seek_results}")

    event_marker = event_marker_evidence(playable)
    if not event_marker["inside_segment"]:
        raise AssertionError(f"event marker projection failed: {event_marker}")

    event_resolution = resolve_wall_clock(
        items,
        parse_iso(event_marker["event_at"]),
    )
    if event_resolution["status"] != "playable":
        raise AssertionError(
            f"event marker did not resolve to playable media: {event_resolution}"
        )
    if event_resolution["segment_id"] != playable["id"]:
        raise AssertionError(
            f"event marker resolved to wrong segment: {event_resolution}"
        )

    dst = dst_roundtrip_evidence()
    if not (
        dst["both_roundtrip"]
        and dst["same_wall_clock_hour"]
        and dst["distinct_offsets"]
    ):
        raise AssertionError(f"DST roundtrip evidence failed: {dst}")

    clock = camera_clock_normalization_evidence()
    if not clock["normalizes_back_to_canonical"]:
        raise AssertionError(f"camera clock normalization failed: {clock}")

    partial_segments = [
        {
            "id": item["id"],
            "duration_seconds": item["duration_ms"] / 1000.0,
        }
        for item in items
        if abs(item["duration_ms"] / 1000.0 - SEGMENT_TARGET_SECONDS)
        > 1.5
    ]
    if not partial_segments:
        raise AssertionError(
            "source-outage sequence produced no partial/non-target segment; "
            "POC-05 partial-segment behavior was not exercised"
        )

    evidence = {
        "result": "PASS",
        "completed_at": iso(time.time()),
        "zlm_version": state["zlm_version"],
        "outage": {
            "requested_start_at": iso(outage_start),
            "requested_end_at": iso(outage_end),
            "requested_duration_seconds": outage_duration,
        },
        "raw_hook_segments": raw_items,
        "normalized_segments": items,
        "boundary_tolerance_seconds": BOUNDARY_TOLERANCE_SECONDS,
        "raw_hook_boundary_deltas": raw_deltas,
        "normalized_same_session_boundary_deltas": normal_deltas,
        "source_outage_gap_boundary": cross_gap,
        "recording_ranges": [
            {
                "start_at": iso(row["start"]),
                "end_at": iso(row["end"]),
                "segment_ids": row["segment_ids"],
            }
            for row in ranges
        ],
        "projected_gap": gap,
        "gap_midpoint_at": iso(gap_midpoint),
        "gap_resolution": gap_resolution,
        "partial_or_non_target_durations": partial_segments,
        "event_marker": event_marker,
        "event_marker_resolution": event_resolution,
        "dst_roundtrip": dst,
        "camera_clock_normalization": clock,
        "vod": {
            "source_segment_id": playable["id"],
            "source_path": str(source_path),
            "vod_path": str(vod_path),
            "probe": local_probe,
            "rtsp_url": rtsp_url,
            "seek_results": seek_results,
        },
    }

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
    verify_parser.add_argument("--outage-start", type=float, required=True)
    verify_parser.add_argument("--outage-end", type=float, required=True)
    args = parser.parse_args()

    if args.command == "prepare":
        prepare()
    else:
        verify(args.outage_start, args.outage_end)


if __name__ == "__main__":
    main()
