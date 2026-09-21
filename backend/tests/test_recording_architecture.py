from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

NORMAL_RECORDING_PATHS = (
    ROOT / "app/modules/recordings/runtime.py",
    ROOT / "app/modules/recordings/prebuffer.py",
    ROOT / "app/integrations/zlm/recording.py",
)

FORBIDDEN_NORMAL_PATH_TERMS = (
    "ffmpeg",
    "ffprobe",
    "subprocess",
)


def test_normal_recording_path_has_no_ffmpeg_process_boundary() -> None:
    for path in NORMAL_RECORDING_PATHS:
        source = path.read_text(
            encoding="utf-8"
        ).lower()
        for term in FORBIDDEN_NORMAL_PATH_TERMS:
            assert term not in source, (
                f"{path.relative_to(ROOT)} must keep "
                f"{term!r} out of the normal recording path"
            )


def test_recovery_probe_is_confined_to_reconciliation() -> None:
    source = (
        ROOT
        / "app/modules/recordings/reconciliation.py"
    ).read_text(
        encoding="utf-8"
    ).lower()

    assert "ffprobe" in source
    assert "recording recovery ffprobe failed" in source
