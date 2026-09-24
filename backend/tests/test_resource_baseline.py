from __future__ import annotations

from pathlib import Path

from app import cli
from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import Camera


def make_database(
    tmp_path: Path,
) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key=(
            "resource-baseline-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'resource.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_require_tmpfs=False,
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def test_resource_baseline_requires_clean_camera_inventory(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        clean = cli._resource_baseline_status(
            settings,
            database,
        )
        assert clean["passed"] is True
        assert clean["configured_cameras"] == 0
        assert clean["enabled_cameras"] == 0

        with database.session() as session:
            session.add(
                Camera(
                    channel_key="clean-core-test",
                    name="Configured camera",
                    enabled=False,
                )
            )
            session.commit()

        configured = cli._resource_baseline_status(
            settings,
            database,
        )
        assert configured["passed"] is False
        assert configured["configured_cameras"] == 1
        assert configured["enabled_cameras"] == 0
    finally:
        database.close()
