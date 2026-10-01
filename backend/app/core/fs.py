"""Filesystem primitives shared by product modules, adapters, and the CLI.

Host-mutating code previously re-implemented "write a temp file, flush it, then
rename over the target" eight times, with silently different durability
guarantees: four of the eight copies never called ``fsync``, so a power loss
could leave a truncated state file that the next boot trusted. The worker
heartbeat was worse: it reused the fixed name ``worker-heartbeat.tmp``, so two
concurrent writers opened the same file and each renamed a half-written file
over the target.

Both properties matter for zero-nvr because these files are *recovery inputs*
(managed Frigate config, recovery-kit envelopes, the worker heartbeat, CLI
database snapshots). A caller that cannot state its durability requirement
should not be writing them by hand, so this module is the single implementation:

* ``atomic_write_*`` — unique temp name, fsync, then rename;
* ``replace_durably`` — for callers that already produced and verified a file
  (recording-fragment promotion, CLI snapshots) and only need the flush + move;
* ``resolve_within`` / ``resolve_within_or_none`` — path containment, which was
  likewise re-implemented as seven named private helpers plus four inline
  copies with drift between "raise a domain error" and "return None".

Containment raises :class:`PathEscapeError` rather than a module-specific error
so the caller keeps ownership of its own error code while the check itself stays
in one place.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


class PathEscapeError(ValueError):
    """A resolved path escaped the root it was required to stay within.

    Subclasses ``ValueError`` so existing call sites that already catch
    ``ValueError`` around a containment check keep working.
    """


def _unique_temporary(path: Path) -> Path:
    """Return a sibling temp path that cannot collide between writers.

    Uniqueness is what makes the following ``os.replace`` atomic in practice.
    With a deterministic name two writers share one temp file, so one of them
    can rename a partially written file over the target.
    """
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")


def fsync_path(path: Path) -> None:
    """Flush an existing file's contents to stable storage."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(
    path: Path,
    payload: bytes,
    *,
    mode: int | None = None,
) -> Path:
    """Write ``payload`` to ``path`` atomically, optionally forcing a file mode.

    ``os.open`` is subject to the process umask, so a requested ``mode`` is
    applied with an explicit ``chmod`` before the rename. Credential-bearing
    files rely on that (rclone config 0o600, camera acceptance state 0o640).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _unique_temporary(path)
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        mode if mode is not None else 0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def atomic_write_text(
    path: Path,
    text: str,
    *,
    mode: int | None = None,
    encoding: str = "utf-8",
) -> Path:
    """Text variant of :func:`atomic_write_bytes`."""
    return atomic_write_bytes(path, text.encode(encoding), mode=mode)


def atomic_write_json(
    path: Path,
    value: Any,
    *,
    mode: int | None = None,
    sort_keys: bool = True,
    trailing_newline: bool = False,
) -> Path:
    """JSON variant used for state and manifest files.

    ``sort_keys`` and the trailing newline are preserved as options because
    existing on-disk artefacts were written with both conventions and the
    readers compare content rather than re-serialising it.
    """
    text = json.dumps(value, sort_keys=sort_keys)
    if trailing_newline:
        text += "\n"
    return atomic_write_text(path, text, mode=mode)


def replace_durably(
    source: Path,
    destination: Path,
    *,
    mode: int | None = None,
) -> Path:
    """Flush ``source`` and move it over ``destination``.

    For callers that already wrote and *verified* a file elsewhere (fragment
    promotion checks the byte count, CLI snapshots verify the SQLite image) and
    only need the durability step plus the rename.
    """
    source = Path(source)
    destination = Path(destination)
    if mode is not None:
        os.chmod(source, mode)
    fsync_path(source)
    os.replace(source, destination)
    return destination


def resolve_within(root: Path, candidate: Path | str) -> Path:
    """Resolve ``candidate`` and require it to stay inside ``root``.

    Relative candidates are interpreted against ``root``. ``strict=False`` keeps
    this usable for paths that do not exist yet (export targets, staging dirs)
    while still resisting ``..`` traversal and absolute-path injection.
    """
    resolved_root = Path(root).expanduser().resolve(strict=False)
    target = Path(candidate)
    if not target.is_absolute():
        target = resolved_root / target
    try:
        resolved = target.expanduser().resolve(strict=False)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        # OSError covers symlink loops and unreadable parents; ValueError is the
        # relative_to() rejection. Both mean "not contained".
        raise PathEscapeError(
            f"path {candidate!s} escapes {resolved_root}"
        ) from exc
    return resolved


def resolve_within_or_none(
    root: Path,
    candidate: Path | str,
) -> Path | None:
    """Non-raising :func:`resolve_within` for callers that treat escape as "skip"."""
    try:
        return resolve_within(root, candidate)
    except PathEscapeError:
        return None
