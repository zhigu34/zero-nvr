from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.service import CameraService
from app.modules.recordings.arbiter import (
    RecordingArbiterService,
)
from app.modules.recordings.models import (
    RecordingPolicy,
    RecordingTrigger,
)


def make_database(
    tmp_path: Path,
) -> tuple[Settings, Database]:
    settings = Settings(
        secret_key=(
            "recording-arbiter-test-secret-"
            "key-32-bytes-minimum"
        ),
        database_url=(
            f"sqlite:///{tmp_path / 'arbiter.db'}"
        ),
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed_camera(
    settings: Settings,
    database: Database,
):
    with database.session() as session:
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
        session.commit()
        return camera.id


def add_trigger(
    database: Database,
    *,
    camera_id,
    trigger_type: str,
    now: datetime,
    end_offset: int | None = 20,
) -> None:
    with database.session() as session:
        session.add(
            RecordingTrigger(
                camera_id=camera_id,
                type=trigger_type,
                source="test",
                requested_at=now,
                pre_roll_seconds=10,
                post_roll_seconds=10,
                planned_start_at=(
                    now - timedelta(seconds=10)
                ),
                planned_end_at=(
                    now
                    + timedelta(
                        seconds=end_offset
                    )
                    if end_offset is not None
                    else None
                ),
                state=(
                    "ACTIVE"
                    if end_offset is None
                    else "COMPLETED"
                ),
                reason="test",
                correlation_id=(
                    f"test-{trigger_type}-"
                    f"{end_offset}"
                ),
                metadata_json={},
            )
        )
        session.commit()


def test_event_only_trigger_keeps_rolling_prebuffer(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path
    )
    try:
        camera_id = seed_camera(
            settings,
            database,
        )
        now = datetime(
            2026,
            9,
            21,
            9,
            0,
            tzinfo=UTC,
        )
        with database.session() as session:
            policy = RecordingPolicy(
                camera_id=camera_id,
                baseline_mode="disabled",
                event_recording_enabled=True,
                enabled=True,
            )
            session.add(policy)
            session.commit()
            policy_id = policy.id

        with database.session() as session:
            policy = session.get(
                RecordingPolicy,
                policy_id,
            )
            assert policy is not None
            idle = RecordingArbiterService.evaluate(
                session,
                camera_id=camera_id,
                camera_enabled=True,
                policy=policy,
                at=now,
            )
            assert idle.mode == "prebuffer"
            assert idle.reasons == ()

        add_trigger(
            database,
            camera_id=camera_id,
            trigger_type="AI_OBJECT",
            now=now,
        )

        with database.session() as session:
            policy = session.get(
                RecordingPolicy,
                policy_id,
            )
            assert policy is not None
            active = RecordingArbiterService.evaluate(
                session,
                camera_id=camera_id,
                camera_enabled=True,
                policy=policy,
                at=now,
            )
            assert active.mode == "prebuffer"
            assert active.reasons == ("event",)
            assert active.event_active is True

            expired = RecordingArbiterService.evaluate(
                session,
                camera_id=camera_id,
                camera_enabled=True,
                policy=policy,
                at=(
                    now
                    + timedelta(seconds=21)
                ),
            )
            assert expired.mode == "prebuffer"
            assert expired.reasons == ()
    finally:
        database.close()


def test_manual_trigger_requires_persistent(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path
    )
    try:
        camera_id = seed_camera(
            settings,
            database,
        )
        now = datetime(
            2026,
            9,
            21,
            9,
            0,
            tzinfo=UTC,
        )
        with database.session() as session:
            policy = RecordingPolicy(
                camera_id=camera_id,
                baseline_mode="disabled",
                event_recording_enabled=True,
                enabled=True,
            )
            session.add(policy)
            session.commit()
            policy_id = policy.id

        add_trigger(
            database,
            camera_id=camera_id,
            trigger_type="MANUAL",
            now=now,
            end_offset=None,
        )

        with database.session() as session:
            policy = session.get(
                RecordingPolicy,
                policy_id,
            )
            assert policy is not None
            decision = RecordingArbiterService.evaluate(
                session,
                camera_id=camera_id,
                camera_enabled=True,
                policy=policy,
                at=now,
            )
            assert decision.mode == "persistent"
            assert decision.reasons == ("manual",)
            assert decision.manual_active is True
            assert decision.event_active is False
    finally:
        database.close()


def test_continuous_and_event_are_additive_and_idempotent(
    tmp_path: Path,
) -> None:
    settings, database = make_database(
        tmp_path
    )
    try:
        camera_id = seed_camera(
            settings,
            database,
        )
        now = datetime(
            2026,
            9,
            21,
            9,
            0,
            tzinfo=UTC,
        )
        with database.session() as session:
            policy = RecordingPolicy(
                camera_id=camera_id,
                baseline_mode="continuous",
                event_recording_enabled=True,
                enabled=True,
            )
            session.add(policy)
            session.commit()
            policy_id = policy.id

        add_trigger(
            database,
            camera_id=camera_id,
            trigger_type="AI_OBJECT",
            now=now,
        )

        with database.session() as session:
            policy = session.get(
                RecordingPolicy,
                policy_id,
            )
            assert policy is not None
            first = RecordingArbiterService.evaluate(
                session,
                camera_id=camera_id,
                camera_enabled=True,
                policy=policy,
                at=now,
            )
            second = RecordingArbiterService.evaluate(
                session,
                camera_id=camera_id,
                camera_enabled=True,
                policy=policy,
                at=now,
            )
            assert first == second
            assert first.mode == "persistent"
            assert first.reasons == (
                "continuous",
                "event",
            )
    finally:
        database.close()
