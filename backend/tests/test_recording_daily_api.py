from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingSegment
from tests.factories import make_test_app

ADMIN_PASSWORD = "correct-horse-battery-staple"


def make_app(tmp_path: Path):
    return make_test_app(
        tmp_path,
        secret_key="recording-daily-api-test-secret-key-32-bytes-min",
        database_url=f"sqlite:///{tmp_path / 'daily-api.db'}",
        recordings_dir=tmp_path / "recordings",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
    )


def setup_admin(client: TestClient) -> None:
    created = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": "admin",
            "display_name": "Administrator",
            "password": ADMIN_PASSWORD,
        },
    )
    assert created.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200


def seed(app, rows: list[tuple[datetime, int, int]]) -> uuid.UUID:
    """rows: (started_at, duration_ms, size_bytes)."""
    with app.state.database.session() as session:
        camera = CameraService(
            app.state.settings
        ).create_manual_rtsp_camera(
            session,
            name="Front Door",
            location=None,
            storage_label=None,
            primary_name="Main",
            primary_url="rtsp://camera.local/main",
            secondary_name=None,
            secondary_url=None,
        )
        for started_at, duration_ms, size_bytes in rows:
            session.add(
                RecordingSegment(
                    camera_id=camera.id,
                    stream_profile_id=None,
                    started_at=started_at,
                    ended_at=started_at + timedelta(milliseconds=duration_ms),
                    duration_ms=duration_ms,
                    timing_status="FINAL",
                    timing_source="EXPLICIT_STOP",
                    recording_reasons_json=["baseline"],
                    size_bytes=size_bytes,
                    codec="H264",
                    container="mp4",
                    source_media_server_id="zlm",
                    source_app="zero-nvr",
                    source_stream="main",
                    integrity_status="OK",
                    completion_reason=None,
                )
            )
        session.commit()
        return camera.id


def daily(
    client: TestClient,
    camera_id: uuid.UUID,
    start: datetime,
    end: datetime,
    time_zone: str = "UTC",
):
    return client.get(
        f"/api/v1/cameras/{camera_id}/recordings/daily",
        params={
            "from": start.isoformat(),
            "to": end.isoformat(),
            "time_zone": time_zone,
        },
    )


def test_groups_by_local_day_and_sums_real_columns(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    client = TestClient(app)
    setup_admin(client)

    # Two segments inside 2026-10-01 UTC, one inside 10-02.
    camera_id = seed(
        app,
        [
            (datetime(2026, 10, 1, 1, 0, tzinfo=UTC), 30_000, 1_000),
            (datetime(2026, 10, 1, 23, 0, tzinfo=UTC), 20_000, 2_000),
            (datetime(2026, 10, 2, 5, 0, tzinfo=UTC), 10_000, 4_000),
        ],
    )
    response = daily(
        client,
        camera_id,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 3, tzinfo=UTC),
    )
    assert response.status_code == 200
    assert response.json() == [
        {
            "day": "2026-10-01",
            "count": 2,
            "duration_sec": 50,
            "size_bytes": 3_000,
        },
        {
            "day": "2026-10-02",
            "count": 1,
            "duration_sec": 10,
            "size_bytes": 4_000,
        },
    ]


def test_day_is_local_not_utc(tmp_path: Path) -> None:
    """A 16:00Z segment is the *next* local day in Asia/Shanghai."""
    app = make_app(tmp_path)
    client = TestClient(app)
    setup_admin(client)
    camera_id = seed(
        app,
        [(datetime(2026, 10, 1, 16, 30, tzinfo=UTC), 60_000, 5_000)],
    )
    response = daily(
        client,
        camera_id,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 3, tzinfo=UTC),
        time_zone="Asia/Shanghai",
    )
    assert response.status_code == 200
    assert [row["day"] for row in response.json()] == ["2026-10-02"]


def test_days_without_recordings_are_omitted(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    client = TestClient(app)
    setup_admin(client)
    camera_id = seed(
        app,
        [(datetime(2026, 10, 1, 1, 0, tzinfo=UTC), 1_000, 1)],
    )
    response = daily(
        client,
        camera_id,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 20, tzinfo=UTC),
    )
    assert response.status_code == 200
    # Sparse, not a run of zeroes: a calendar wants to know which days have
    # material, and a caller would have to filter zero rows back out.
    assert len(response.json()) == 1


def test_dst_short_day_does_not_swallow_the_next_morning(
    tmp_path: Path,
) -> None:
    """2026-03-08 is 23 hours long in New York."""
    app = make_app(tmp_path)
    client = TestClient(app)
    setup_admin(client)
    # 06:00Z on 03-08 is 01:00 EST — still the 8th. 04:00Z on 03-09 is 00:00 EDT.
    camera_id = seed(
        app,
        [
            (datetime(2026, 3, 8, 6, 0, tzinfo=UTC), 1_000, 1),
            (datetime(2026, 3, 9, 4, 30, tzinfo=UTC), 1_000, 1),
        ],
    )
    response = daily(
        client,
        camera_id,
        datetime(2026, 3, 8, tzinfo=UTC),
        datetime(2026, 3, 10, tzinfo=UTC),
        time_zone="America/New_York",
    )
    assert response.status_code == 200
    assert [row["day"] for row in response.json()] == ["2026-03-08", "2026-03-09"]


def test_rejects_an_unknown_timezone(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    client = TestClient(app)
    setup_admin(client)
    camera_id = seed(app, [])
    # `client` is anonymous-free? No: it holds the admin cookie from setup_admin.
    # This test asserts the opposite, so use a second, never-logged-in client.
    response = daily(
        client,
        camera_id,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 2, tzinfo=UTC),
        time_zone="Mars/Olympus",
    )
    # Silently falling back to UTC would mislabel every day for the operator.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "recording_daily_timezone_invalid"


def test_rejects_an_inverted_range(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    client = TestClient(app)
    setup_admin(client)
    camera_id = seed(app, [])
    # `client` is anonymous-free? No: it holds the admin cookie from setup_admin.
    # This test asserts the opposite, so use a second, never-logged-in client.
    response = daily(
        client,
        camera_id,
        datetime(2026, 10, 2, tzinfo=UTC),
        datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert response.status_code == 422


def test_caps_the_range(tmp_path: Path) -> None:
    """One aggregate query runs per local day, so the range must be bounded."""
    app = make_app(tmp_path)
    client = TestClient(app)
    setup_admin(client)
    camera_id = seed(app, [])
    # `client` is anonymous-free? No: it holds the admin cookie from setup_admin.
    # This test asserts the opposite, so use a second, never-logged-in client.
    response = daily(
        client,
        camera_id,
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert response.status_code == 422
    assert (
        response.json()["error"]["code"]
        == "recording_daily_range_too_large"
    )


def test_requires_recording_view(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    client = TestClient(app)
    setup_admin(client)
    camera_id = seed(app, [])
    # `client` holds the admin cookie from setup_admin, so the unauthenticated
    # case needs a second client that was never logged in.
    anonymous = TestClient(app)
    response = anonymous.get(
        f"/api/v1/cameras/{camera_id}/recordings/daily",
        params={
            "from": datetime(2026, 10, 1, tzinfo=UTC).isoformat(),
            "to": datetime(2026, 10, 2, tzinfo=UTC).isoformat(),
        },
    )
    assert response.status_code in (401, 403)
