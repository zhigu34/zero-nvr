from __future__ import annotations

import os
from pathlib import Path

from huey import SqliteHuey


def _queue_path() -> Path:
    return Path(
        os.getenv(
            "ZERO_NVR_HUEY_DB_PATH",
            "/var/lib/zero-nvr/huey.db",
        )
    )


path = _queue_path()
path.parent.mkdir(parents=True, exist_ok=True)

huey = SqliteHuey(
    "zero-nvr",
    filename=str(path),
    results=False,
    utc=True,
)
