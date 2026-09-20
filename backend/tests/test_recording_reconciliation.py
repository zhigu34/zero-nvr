from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingSegment,
)
from app.modules.recordings.reconciliation import (
    RecoveredMediaProbe,
    RecordingCatalogReconciliationService,
)
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)


def make_database(
    tmp_path: Path,
) -> tuple[
    Settings,
    Database,
    Path,
]:
    root = tmp_path / "recordings"
    root.mkdir()
    settings = Settings(
        secret_key=(
            "reconciliation-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
        database_url=(
            f"sqlite:///{tmp_path / 'reconcile.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        recordings_dir=root,
    )
    database = Database(settings)
    Base.metadata.create_all(
        database.engine
    )
    return settings, database, root


def seed_camera(
    settings: Settings,
    database: Database,
    root: Path,
):
    with database.session() as session:
        target = StorageTarget(
            name="Local",
            type="local",
            role="recording",
            enabled=True,
            config_json={
                "path": str(root),
                "default_recording": True,
            },
        )
        session.add(target)
        camera = CameraService(
            settings
        ).create_manual_rtsp_camera(
            session,
            name="Front Door",
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url=(
                "rtsp://camera.local/main"
            ),
            secondary_name=None,
            secondary_url=None,
        )
        session.add(
            RecordingPolicy(
                camera_id=camera.id,
                baseline_mode="continuous",
                schedule_json={},
                schedule_timezone=None,
                event_recording_enabled=False,
                event_filter_json={},
                segment_target_seconds=300,
                pre_roll_seconds=10,
                post_roll_seconds=10,
                storage_target_id=None,
                retention_policy_id=None,
                enabled=True,
            )
        )
        record_binding = next(
            item
            for item in camera.stream_bindings
            if item.purpose == "RECORD"
        )
        session.commit()
        return (
            camera.id,
            record_binding.stream_profile_id,
            target.id,
        )


def orphan(
    root: Path,
    profile_id,
    *,
    second: int,
    size: int = 4096,
) -> Path:
    date = "2026-09-20"
    directory = (
        root
        / "record"
        / "zero-nvr"
        / f"profile-{profile_id.hex}"
        / date
    )
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    path = (
        directory
        / (
            "2026-09-20-12-00-"
            f"{second:02d}-0.mp4"
        )
    )
    path.write_bytes(
        b"x" * size
    )
    old = (
        datetime.now(UTC)
        - timedelta(minutes=5)
    ).timestamp()
    os.utime(
        path,
        (old, old),
    )
    return path


def probe(
    _path: Path,
) -> RecoveredMediaProbe:
    return RecoveredMediaProbe(
        duration_ms=10_000,
        codec="h264",
    )


def test_reconciliation_recovers_proven_orphan_and_is_idempotent(
    tmp_path: Path,
) -> None:
    settings, database, root = (
        make_database(tmp_path)
    )
    try:
        (
            camera_id,
            profile_id,
            target_id,
        ) = seed_camera(
            settings,
            database,
            root,
        )
        proven = orphan(
            root,
            profile_id,
            second=0,
        )
        ambiguous = (
            root
            / "orphans"
            / "mystery.mp4"
        )
        ambiguous.parent.mkdir()
        ambiguous.write_bytes(
            b"mystery"
        )
        old = (
            datetime.now(UTC)
            - timedelta(minutes=5)
        ).timestamp()
        os.utime(
            ambiguous,
            (old, old),
        )

        service = (
            RecordingCatalogReconciliationService(
                settings,
                probe=probe,
            )
        )
        first = service.reconcile(
            database,
            full=True,
        )
        assert first.recovered == 1
        assert first.ambiguous == 1
        assert proven.is_file()
        assert ambiguous.is_file()

        with database.session() as session:
            assert session.scalar(
                select(func.count())
                .select_from(
                    RecordingSegment
                )
            ) == 1
            location = session.scalar(
                select(
                    RecordingLocation
                ).where(
                    RecordingLocation.storage_target_id
                    == target_id
                )
            )
            assert location is not None
            assert (
                location.object_path
                == proven.relative_to(
                    root
                ).as_posix()
            )
            assert (
                location.state
                == "AVAILABLE"
            )
            segment = session.get(
                RecordingSegment,
                location.recording_segment_id,
            )
            assert segment is not None
            assert (
                segment.camera_id
                == camera_id
            )
            assert (
                segment.timing_source
                == "RECOVERY"
            )
            assert (
                segment.integrity_status
                == "OK"
            )
            session.commit()

        second = service.reconcile(
            database,
            full=True,
        )
        assert second.recovered == 0
        assert second.relinked == 0
        assert second.missing == 0
        assert second.ambiguous == 1
        with database.session() as session:
            assert session.scalar(
                select(func.count())
                .select_from(
                    RecordingSegment
                )
            ) == 1
            session.commit()
    finally:
        database.close()


def test_reconciliation_marks_missing_and_relinks_exact_file(
    tmp_path: Path,
) -> None:
    settings, database, root = (
        make_database(tmp_path)
    )
    try:
        (
            _camera_id,
            profile_id,
            target_id,
        ) = seed_camera(
            settings,
            database,
            root,
        )
        path = orphan(
            root,
            profile_id,
            second=10,
        )
        service = (
            RecordingCatalogReconciliationService(
                settings,
                probe=probe,
            )
        )
        assert service.reconcile(
            database,
            full=True,
        ).recovered == 1

        object_path = (
            path.relative_to(
                root
            ).as_posix()
        )
        path.unlink()

        missing = service.reconcile(
            database,
            full=True,
        )
        assert missing.missing == 1
        with database.session() as session:
            location = session.scalar(
                select(
                    RecordingLocation
                ).where(
                    RecordingLocation.storage_target_id
                    == target_id,
                    RecordingLocation.object_path
                    == object_path,
                )
            )
            assert location is not None
            assert (
                location.state
                == "MISSING"
            )
            session.commit()

        path.write_bytes(
            b"x" * 4096
        )
        old = (
            datetime.now(UTC)
            - timedelta(minutes=5)
        ).timestamp()
        os.utime(
            path,
            (old, old),
        )
        relinked = service.reconcile(
            database,
            full=False,
        )
        assert relinked.relinked == 1
        with database.session() as session:
            location = session.scalar(
                select(
                    RecordingLocation
                ).where(
                    RecordingLocation.storage_target_id
                    == target_id,
                    RecordingLocation.object_path
                    == object_path,
                )
            )
            assert location is not None
            assert (
                location.state
                == "AVAILABLE"
            )
            session.commit()
    finally:
        database.close()


def test_reconciliation_restart_after_committed_mutation_is_safe(
    tmp_path: Path,
) -> None:
    settings, database, root = (
        make_database(tmp_path)
    )
    try:
        (
            _camera_id,
            profile_id,
            _target_id,
        ) = seed_camera(
            settings,
            database,
            root,
        )
        orphan(
            root,
            profile_id,
            second=20,
        )
        orphan(
            root,
            profile_id,
            second=30,
        )

        mutations = 0

        def crash() -> None:
            nonlocal mutations
            mutations += 1
            if mutations == 1:
                raise RuntimeError(
                    "simulated worker crash"
                )

        with pytest.raises(
            RuntimeError,
            match="simulated worker crash",
        ):
            RecordingCatalogReconciliationService(
                settings,
                probe=probe,
                mutation_hook=crash,
            ).reconcile(
                database,
                full=True,
            )

        converged = (
            RecordingCatalogReconciliationService(
                settings,
                probe=probe,
            ).reconcile(
                database,
                full=True,
            )
        )
        assert converged.recovered == 1

        idempotent = (
            RecordingCatalogReconciliationService(
                settings,
                probe=probe,
            ).reconcile(
                database,
                full=True,
            )
        )
        assert idempotent.recovered == 0

        with database.session() as session:
            assert session.scalar(
                select(func.count())
                .select_from(
                    RecordingSegment
                )
            ) == 2
            session.commit()
    finally:
        database.close()
