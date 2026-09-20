from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.internal.zlm_hooks as zlm_hooks
from app.core.config import Settings
from app.core.db import Base
from app.integrations.zlm import ZlmMediaAccess
from app.main import create_app
from app.modules.cameras.models import CameraStreamProfile
from app.modules.cameras.service import CameraService
from app.modules.recordings.models import RecordingPolicy, RecordingSegment
from app.modules.storage.models import RecordingLocation, StorageTarget


HOOK_SECRET = "h" * 40


def dt(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


def make_app(tmp_path: Path, *, hook_secret: str | None = HOOK_SECRET):
    tmp_path.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        secret_key="zlm-hook-test-secret-key-32-bytes-minimum",
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'zlm-hooks.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        prebuffer_dir=tmp_path / "prebuffer",
        prebuffer_require_tmpfs=False,
        session_cookie_secure=False,
        zlm_hook_secret=hook_secret,
    )
    settings.prebuffer_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def seed_recording_camera(app) -> tuple[str, str]:
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
        target = StorageTarget(
            name="Local Recording",
            type="local",
            role="recording",
            enabled=True,
            config_json={
                "path": "/recordings",
                "default_recording": True,
            },
        )
        session.add(target)
        session.flush()

        profile_id = session.scalar(
            select(CameraStreamProfile.id).where(
                CameraStreamProfile.camera_id == camera.id,
                CameraStreamProfile.adapter_profile_key == "manual-primary",
            )
        )
        assert profile_id is not None

        session.add(
            RecordingPolicy(
                camera_id=camera.id,
                baseline_mode="continuous",
                event_recording_enabled=False,
                storage_target_id=target.id,
                enabled=True,
            )
        )
        session.commit()

    return str(camera.id), f"profile-{profile_id.hex}"


def stream_changed_payload(
    *,
    stream: str,
    regist: bool,
    schema: str = "rtsp",
    app: str = "zero-nvr",
    secret: str = HOOK_SECRET,
) -> dict[str, object]:
    return {
        "mediaServerId": secret,
        "schema": schema,
        "vhost": "__defaultVhost__",
        "app": app,
        "stream": stream,
        "regist": regist,
    }


def record_payload(
    *,
    stream: str,
    start: float,
    duration: float,
    name: str,
    size: int = 1_000_000,
    secret: str = HOOK_SECRET,
) -> dict[str, object]:
    return {
        "mediaServerId": secret,
        "vhost": "__defaultVhost__",
        "app": "zero-nvr",
        "stream": stream,
        "start_time": start,
        "time_len": duration,
        "file_size": size,
        "file_path": f"/recordings/front-door/{name}",
    }


def test_hook_authentication_is_required_and_sanitized(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    _camera_id, stream = seed_recording_camera(app)

    with TestClient(app) as client:
        wrong = client.post(
            "/internal/hooks/zlm/stream-changed",
            json=stream_changed_payload(
                stream=stream,
                regist=True,
                secret="x" * 40,
            ),
        )
        assert wrong.status_code == 401
        assert wrong.json()["error"]["code"] == "zlm_hook_unauthorized"
        assert HOOK_SECRET not in wrong.text

    no_secret_app = make_app(
        tmp_path / "unconfigured",
        hook_secret=None,
    )
    with TestClient(no_secret_app) as client:
        missing = client.post(
            "/internal/hooks/zlm/stream-changed",
            json=stream_changed_payload(
                stream=stream,
                regist=True,
            ),
        )
        assert missing.status_code == 503
        assert missing.json()["error"]["code"] == "zlm_hook_not_configured"


def test_non_rtsp_or_unmanaged_stream_change_does_not_create_continuity(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    _camera_id, stream = seed_recording_camera(app)

    with TestClient(app) as client:
        hls = client.post(
            "/internal/hooks/zlm/stream-changed",
            json=stream_changed_payload(
                stream=stream,
                regist=True,
                schema="hls",
            ),
        )
        assert hls.status_code == 200
        assert hls.json()["code"] == 0

        foreign = client.post(
            "/internal/hooks/zlm/stream-changed",
            json=stream_changed_payload(
                stream=stream,
                regist=True,
                app="other-app",
            ),
        )
        assert foreign.status_code == 200

    assert app.state.zlm_continuity.current(
        vhost="__defaultVhost__",
        app="zero-nvr",
        stream=stream,
    ) is None


def test_record_hooks_normalize_only_with_proven_same_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    _camera_id, stream = seed_recording_camera(app)

    clock = iter([dt(1000)])
    monkeypatch.setattr(zlm_hooks, "utc_now", lambda: next(clock))

    with TestClient(app) as client:
        registered = client.post(
            "/internal/hooks/zlm/stream-changed",
            json=stream_changed_payload(
                stream=stream,
                regist=True,
            ),
        )
        assert registered.status_code == 200

        first = client.post(
            "/internal/hooks/zlm/record-mp4",
            json=record_payload(
                stream=stream,
                start=1001,
                duration=8,
                name="001.mp4",
            ),
        )
        assert first.status_code == 200

        second = client.post(
            "/internal/hooks/zlm/record-mp4",
            json=record_payload(
                stream=stream,
                start=1010,
                duration=8,
                name="002.mp4",
            ),
        )
        assert second.status_code == 200

        retry = client.post(
            "/internal/hooks/zlm/record-mp4",
            json=record_payload(
                stream=stream,
                start=1010,
                duration=8,
                name="002.mp4",
            ),
        )
        assert retry.status_code == 200

    with app.state.database.session() as session:
        rows = list(
            session.scalars(
                select(RecordingSegment).order_by(
                    RecordingSegment.started_at
                )
            )
        )
        assert len(rows) == 2
        assert rows[0].started_at == dt(1002)
        assert rows[0].ended_at == dt(1010)
        assert rows[0].timing_status == "FINAL"
        assert rows[0].timing_source == "NEXT_SEGMENT_BOUNDARY"

        assert rows[1].started_at == dt(1010)
        assert rows[1].ended_at == dt(1018)
        assert rows[1].timing_status == "PROVISIONAL"

        assert session.scalar(
            select(func.count()).select_from(RecordingLocation)
        ) == 2


def test_reconnect_late_old_hook_never_contaminates_new_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    _camera_id, stream = seed_recording_camera(app)

    boundaries = iter([
        dt(2000),  # old register
        dt(2010),  # old unregister
        dt(2012),  # new register
    ])
    monkeypatch.setattr(
        zlm_hooks,
        "utc_now",
        lambda: next(boundaries),
    )

    with TestClient(app) as client:
        assert client.post(
            "/internal/hooks/zlm/stream-changed",
            json=stream_changed_payload(stream=stream, regist=True),
        ).status_code == 200

        assert client.post(
            "/internal/hooks/zlm/record-mp4",
            json=record_payload(
                stream=stream,
                start=2001,
                duration=7,
                name="old-1.mp4",
            ),
        ).status_code == 200

        assert client.post(
            "/internal/hooks/zlm/stream-changed",
            json=stream_changed_payload(stream=stream, regist=False),
        ).status_code == 200

        assert client.post(
            "/internal/hooks/zlm/stream-changed",
            json=stream_changed_payload(stream=stream, regist=True),
        ).status_code == 200

        # New generation gets its own first segment.
        assert client.post(
            "/internal/hooks/zlm/record-mp4",
            json=record_payload(
                stream=stream,
                start=2013,
                duration=7,
                name="new-1.mp4",
            ),
        ).status_code == 200

        # Old generation hook arrives late after reconnect. Its start evidence
        # is before old unregister, so it must resolve to the closed generation.
        assert client.post(
            "/internal/hooks/zlm/record-mp4",
            json=record_payload(
                stream=stream,
                start=2009,
                duration=1,
                name="old-2-late.mp4",
            ),
        ).status_code == 200

        # A second new-generation segment may normalize only new-1.
        assert client.post(
            "/internal/hooks/zlm/record-mp4",
            json=record_payload(
                stream=stream,
                start=2021,
                duration=7,
                name="new-2.mp4",
            ),
        ).status_code == 200

    with app.state.database.session() as session:
        rows = list(
            session.scalars(
                select(RecordingSegment).order_by(
                    RecordingSegment.source_stream,
                    RecordingSegment.started_at,
                )
            )
        )
        assert len(rows) == 4

        by_start = {
            int(row.started_at.timestamp()): row
            for row in rows
        }

        # old-1 normalized only by late old-2 boundary.
        assert by_start[2002].ended_at == dt(2009)
        assert by_start[2002].timing_status == "FINAL"

        # late old tail stays provisional: unregister is a continuity boundary,
        # not exact canonical end-time proof.
        assert by_start[2009].timing_status == "PROVISIONAL"

        # new-1 normalized only by new-2.
        assert by_start[2014].ended_at == dt(2021)
        assert by_start[2014].timing_status == "FINAL"
        assert by_start[2021].timing_status == "PROVISIONAL"



def test_prebuffer_hook_enqueues_without_canonical_segment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = make_app(tmp_path)
    camera_id_text, stream = seed_recording_camera(app)
    import uuid

    camera_id = uuid.UUID(camera_id_text)

    with app.state.database.session() as session:
        policy = session.scalar(
            select(RecordingPolicy).where(
                RecordingPolicy.camera_id == camera_id
            )
        )
        assert policy is not None
        policy.baseline_mode = "disabled"
        policy.event_recording_enabled = True
        session.commit()

    queued = []

    class FakeDispatcher:
        def finalized_prebuffer_fragment(self, fragment):
            queued.append(fragment)

        def reconcile_camera(self, _camera_id):
            return None

    app.state.recording_tasks = FakeDispatcher()

    clock = iter([dt(8000)])
    monkeypatch.setattr(
        zlm_hooks,
        "utc_now",
        lambda: next(clock),
    )

    prebuffer_file = (
        app.state.settings.prebuffer_dir
        / "record"
        / "zero-nvr"
        / stream
        / "2026-09-20"
        / "2026-09-20-00-00-00-0.mp4"
    )

    with TestClient(app) as client:
        assert client.post(
            "/internal/hooks/zlm/stream-changed",
            json=stream_changed_payload(
                stream=stream,
                regist=True,
            ),
        ).status_code == 200

        payload = record_payload(
            stream=stream,
            start=8001,
            duration=5,
            name="ignored-name.mp4",
        )
        payload["file_path"] = str(prebuffer_file)

        response = client.post(
            "/internal/hooks/zlm/record-mp4",
            json=payload,
        )
        assert response.status_code == 200

    assert len(queued) == 1
    assert queued[0].camera_id == camera_id
    assert queued[0].file_path == prebuffer_file

    with app.state.database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(RecordingSegment)
        ) == 0



def test_play_hook_requires_valid_short_lived_media_grant(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    signer = ZlmMediaAccess(app.state.settings)
    signed_url, _expires_at = signer.sign_url(
        "http://media.local/zero-nvr/profile-test/hls.m3u8",
        app="zero-nvr",
        stream="profile-test",
        ttl_seconds=300,
    )
    from urllib.parse import urlsplit

    params = "?" + urlsplit(signed_url).query
    payload = {
        "mediaServerId": HOOK_SECRET,
        "app": "zero-nvr",
        "stream": "profile-test",
        "params": params,
    }

    with TestClient(app) as client:
        allowed = client.post(
            "/internal/hooks/zlm/play",
            json=payload,
        )
        assert allowed.status_code == 200
        assert allowed.json()["code"] == 0

        denied = client.post(
            "/internal/hooks/zlm/play",
            json={
                **payload,
                "params": params.replace("zn_sig=", "zn_sig=bad"),
            },
        )
        assert denied.status_code == 200
        assert denied.json()["code"] != 0

        wrong_stream = client.post(
            "/internal/hooks/zlm/play",
            json={
                **payload,
                "stream": "another-stream",
            },
        )
        assert wrong_stream.status_code == 200
        assert wrong_stream.json()["code"] != 0
