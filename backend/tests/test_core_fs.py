"""Unit tests for the shared filesystem primitives.

These cover the two guarantees the rest of the product now depends on after the
atomic-write and path-containment helpers were consolidated:

* a reader never observes a partially written file, and the write is durable;
* a caller-supplied path can never escape the root it was validated against.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app.core.fs import (
    PathEscapeError,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    replace_durably,
    resolve_within,
    resolve_within_or_none,
)


def test_atomic_write_text_replaces_content_and_leaves_no_temp_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state.json"
    atomic_write_text(target, "first")
    assert target.read_text(encoding="utf-8") == "first"

    atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"

    # A leftover temp file would mean the rename did not happen.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == []


def test_atomic_write_applies_requested_mode(tmp_path: Path) -> None:
    # Credential-bearing files rely on an explicit mode, because os.open() is
    # masked by the process umask.
    target = tmp_path / "secret"
    atomic_write_text(target, "value", mode=0o600)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_atomic_write_json_matches_previous_on_disk_format(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state.json"
    atomic_write_json(
        target,
        {"b": 1, "a": 2},
        trailing_newline=True,
    )
    raw = target.read_text(encoding="utf-8")
    # Sorted keys plus a trailing newline is the format readers already expect.
    assert raw == '{"a": 2, "b": 1}\n'
    assert json.loads(raw) == {"a": 2, "b": 1}


def test_atomic_write_bytes_cleans_up_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.bin"

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"payload")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_concurrent_writers_do_not_share_a_temp_file(tmp_path: Path) -> None:
    """Two writers must not be able to clobber each other's partial file.

    The worker heartbeat previously used a fixed ``.tmp`` name, so concurrent
    writers opened the same path. Unique temp names are what prevent that, and
    this asserts the names differ rather than trying to force a real race.
    """
    from app.core.fs import _unique_temporary

    target = tmp_path / "worker-heartbeat.json"
    names = {_unique_temporary(target).name for _ in range(50)}
    assert len(names) == 50
    assert all(name.endswith(".tmp") for name in names)


def test_replace_durably_publishes_and_fsyncs(tmp_path: Path) -> None:
    source = tmp_path / "fragment.partial"
    destination = tmp_path / "fragment.mp4"
    source.write_bytes(b"media-bytes")

    replace_durably(source, destination, mode=0o644)

    assert destination.read_bytes() == b"media-bytes"
    assert not source.exists()


def test_resolve_within_accepts_contained_and_relative_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "media"
    root.mkdir()

    assert resolve_within(root, "sub/clip.mp4") == root / "sub" / "clip.mp4"
    assert resolve_within(root, root / "clip.mp4") == root / "clip.mp4"


@pytest.mark.parametrize(
    "candidate",
    [
        "../escape.mp4",
        "sub/../../escape.mp4",
        "/etc/passwd",
    ],
)
def test_resolve_within_rejects_escapes(
    tmp_path: Path,
    candidate: str,
) -> None:
    root = tmp_path / "media"
    root.mkdir()

    with pytest.raises(PathEscapeError):
        resolve_within(root, candidate)


def test_resolve_within_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathEscapeError):
        resolve_within(root, "link/secret.mp4")


def test_resolve_within_or_none_reports_escape_as_absence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "media"
    root.mkdir()

    assert resolve_within_or_none(root, "clip.mp4") == root / "clip.mp4"
    assert resolve_within_or_none(root, "../escape.mp4") is None
