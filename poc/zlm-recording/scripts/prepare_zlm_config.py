#!/usr/bin/env python3
"""Patch only the ZLM settings needed by the POC.

The source config is copied from the selected ZLM image so this harness does
not vendor a stale full config.ini.
"""

from __future__ import annotations

import os
from pathlib import Path


SOURCE = Path("/opt/media/conf/config.ini")
TARGET = Path("/out/config.ini")


def set_ini_value(text: str, section: str, key: str, value: str) -> str:
    lines = text.splitlines()
    section_header = f"[{section}]"
    section_start = None
    section_end = len(lines)

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == section_header:
            section_start = idx
            continue
        if section_start is not None and idx > section_start and stripped.startswith("[") and stripped.endswith("]"):
            section_end = idx
            break

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([section_header, f"{key}={value}"])
        return "\n".join(lines) + "\n"

    for idx in range(section_start + 1, section_end):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.split("=", 1)[0].strip() == key:
            lines[idx] = f"{key}={value}"
            return "\n".join(lines) + "\n"

    lines.insert(section_end, f"{key}={value}")
    return "\n".join(lines) + "\n"


def main() -> None:
    secret = os.environ["ZLM_API_SECRET"]
    hook_token = os.environ["ZLM_HOOK_TOKEN"]
    enable_fmp4 = os.getenv("POC_ZLM_ENABLE_FMP4", "0")

    text = SOURCE.read_text(encoding="utf-8")

    patches = [
        ("api", "secret", secret),
        ("general", "mediaServerId", "zero-nvr-poc-zlm"),
        ("hook", "enable", "1"),
        (
            "hook",
            "on_record_mp4",
            f"http://poc-api:8000/internal/hooks/zlm/record-mp4?token={hook_token}",
        ),
        ("record", "enableFmp4", enable_fmp4),
        ("record", "fastStart", "1"),
    ]

    for section, key, value in patches:
        text = set_ini_value(text, section, key, value)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"Wrote {TARGET}; enableFmp4={enable_fmp4}")


if __name__ == "__main__":
    main()
