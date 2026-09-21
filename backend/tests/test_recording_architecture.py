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


def test_native_recording_runtime_does_not_write_media_files() -> None:
    for relative in (
        "app/modules/recordings/runtime.py",
        "app/integrations/zlm/recording.py",
    ):
        source = (ROOT / relative).read_text(
            encoding="utf-8"
        ).lower()
        for term in (
            "shutil.copy",
            "copyfile(",
            "write_bytes(",
            'open("wb',
            "open('wb",
            'open("ab',
            "open('ab",
        ):
            assert term not in source, (
                f"{relative} must leave media-file writing "
                f"to ZLMediaKit; found {term!r}"
            )


def test_post_finalize_file_operations_are_explicitly_bounded() -> None:
    prebuffer = (
        ROOT / "app/modules/recordings/prebuffer.py"
    ).read_text(encoding="utf-8")
    reconciliation = (
        ROOT
        / "app/modules/recordings/reconciliation.py"
    ).read_text(encoding="utf-8")

    # EVENT_ONLY promotion copies only a finalized fragment to a .partial
    # destination, verifies its size, fsyncs it, then publishes atomically.
    assert "shutil.copy2(source, partial)" in prebuffer
    assert "copied_size = partial.stat().st_size" in prebuffer
    assert "os.replace(partial, destination)" in prebuffer

    # Interrupted ZLM finalize recovery does not rewrite media bytes. It
    # reproduces ZLM's final name transition only after probe/settle checks.
    assert "os.link(" in reconciliation
    assert "path.unlink()" in reconciliation
    assert "shutil.copy" not in reconciliation
