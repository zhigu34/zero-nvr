from __future__ import annotations

from pathlib import Path

from app import cli
from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.system.settings import (
    RuntimeTuningSettingsService,
)


def make_database(
    tmp_path: Path,
) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key=(
            "resource-bounds-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'bounds.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
    )
    settings.prebuffer_dir.mkdir(
        parents=True,
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def test_resource_bounds_reports_runtime_cache_quota(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path
    )
    try:
        with database.session() as session:
            RuntimeTuningSettingsService.update(
                session,
                settings=settings,
                changes={
                    "playback_cache_max_bytes": (
                        64 * 1024 * 1024
                    ),
                },
            )
            session.commit()

        playback = (
            settings.cache_dir
            / "playback"
        )
        playback.mkdir(
            parents=True,
        )
        (playback / "one.mp4").write_bytes(
            b"x" * 1024
        )
        (playback / "ignored.lock").write_bytes(
            b"x" * 4096
        )

        value = cli._resource_bounds_status(
            settings,
            database,
        )

        assert (
            value["playback_cache"][
                "media_bytes"
            ]
            == 1024
        )
        assert (
            value["playback_cache"][
                "media_files"
            ]
            == 1
        )
        assert (
            value["playback_cache"][
                "max_bytes"
            ]
            == 64 * 1024 * 1024
        )
        assert (
            value["playback_cache"][
                "within_quota"
            ]
            is True
        )
        assert (
            value["prebuffer"][
                "total_bytes"
            ]
            is not None
        )
    finally:
        database.close()
