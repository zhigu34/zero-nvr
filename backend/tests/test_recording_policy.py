from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.db import Base, Database
from app.core.errors import ApiError
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingPolicy
from app.modules.recordings.policy import RecordingPolicyService


def make_database(tmp_path: Path):
    settings = Settings(
        secret_key="policy-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'policy.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def test_weekly_schedule_normal_and_cross_midnight() -> None:
    policy = RecordingPolicy(
        baseline_mode="schedule",
        schedule_json={
            "weekly": [
                {"days": [0], "start": "09:00", "end": "17:00"},
                {"days": [4], "start": "22:00", "end": "02:00"},
            ]
        },
        schedule_timezone="America/Los_Angeles",
        event_recording_enabled=False,
        enabled=True,
    )

    # Monday local 10:00 PDT.
    assert RecordingPolicyService.baseline_should_record(
        policy,
        at=datetime(2026, 9, 21, 17, 0, tzinfo=UTC),
    )
    # Monday local 18:00 PDT.
    assert not RecordingPolicyService.baseline_should_record(
        policy,
        at=datetime(2026, 9, 22, 1, 0, tzinfo=UTC),
    )
    # Friday 23:00 PDT.
    assert RecordingPolicyService.baseline_should_record(
        policy,
        at=datetime(2026, 9, 26, 6, 0, tzinfo=UTC),
    )
    # Saturday 01:00 PDT belongs to Friday's cross-midnight window.
    assert RecordingPolicyService.baseline_should_record(
        policy,
        at=datetime(2026, 9, 26, 8, 0, tzinfo=UTC),
    )
    # Saturday 03:00 PDT is outside it.
    assert not RecordingPolicyService.baseline_should_record(
        policy,
        at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("schedule", "timezone", "code"),
    [
        ({}, "America/Los_Angeles", "recording_schedule_required"),
        (
            {"weekly": [{"days": [7], "start": "09:00", "end": "17:00"}]},
            "America/Los_Angeles",
            "recording_schedule_invalid",
        ),
        (
            {"weekly": [{"days": [0], "start": "09:00", "end": "09:00"}]},
            "America/Los_Angeles",
            "recording_schedule_invalid",
        ),
        (
            {"weekly": [{"days": [0], "start": "09:00", "end": "17:00"}]},
            "Not/A_Zone",
            "recording_schedule_timezone_invalid",
        ),
    ],
)
def test_invalid_schedule_is_rejected(
    schedule: dict[str, object],
    timezone: str,
    code: str,
) -> None:
    with pytest.raises(ApiError) as captured:
        RecordingPolicyService.validate_schedule(
            baseline_mode="schedule",
            schedule_json=schedule,
            schedule_timezone=timezone,
        )
    assert captured.value.code == code


def test_non_schedule_rejects_schedule_fields() -> None:
    with pytest.raises(ApiError) as captured:
        RecordingPolicyService.validate_schedule(
            baseline_mode="continuous",
            schedule_json={
                "weekly": [
                    {"days": [0], "start": "09:00", "end": "17:00"}
                ]
            },
            schedule_timezone=None,
        )
    assert captured.value.code == "recording_schedule_not_allowed"


def test_policy_put_persists_frozen_axes(tmp_path: Path) -> None:
    settings, database = make_database(tmp_path)
    try:
        with database.session() as session:
            camera = CameraService(settings).create_manual_rtsp_camera(
                session,
                name="Front Door",
                location=None,
                storage_label=None,
                primary_name="Main",
                primary_url="rtsp://camera.local/main",
                secondary_name=None,
                secondary_url=None,
            )
            session.commit()
            camera_id = camera.id

        with database.session() as session:
            policy = RecordingPolicyService.put(
                session,
                camera_id=camera_id,
                values={
                    "baseline_mode": "disabled",
                    "schedule_json": {},
                    "schedule_timezone": None,
                    "event_recording_enabled": True,
                    "event_filter_json": {"labels": ["person"]},
                    "segment_target_seconds": 300,
                    "pre_roll_seconds": 10,
                    "post_roll_seconds": 20,
                    "storage_target_id": None,
                    "retention_policy_id": None,
                    "enabled": True,
                },
            )
            session.commit()

            assert policy.baseline_mode == "disabled"
            assert policy.event_recording_enabled is True
            assert policy.event_filter_json == {"labels": ["person"]}
            assert policy.pre_roll_seconds == 10
            assert policy.post_roll_seconds == 20
    finally:
        database.close()
