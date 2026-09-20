from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.alerts.models import Alert
from app.modules.alerts.service import (
    AlertEvaluationService,
    AlertPolicyService,
)
from app.modules.cameras.service import CameraService
from app.modules.events.service import EventIngest, EventService
from app.modules.notifications.models import NotificationDelivery
from app.modules.notifications.service import NotificationTargetService
from app.modules.recordings.models import RecordingProtection


def make_database(tmp_path: Path):
    settings = Settings(
        secret_key="alert-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'alerts.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed_camera(settings: Settings, database: Database):
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
        return camera.id


def test_alert_evaluation_is_idempotent_cooldown_and_protects_recording(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id = seed_camera(settings, database)

        with database.session() as session:
            target = NotificationTargetService(settings).create(
                session,
                name="Ops",
                enabled=True,
                config={"notify_type": "warning"},
                url="json://example.invalid/token",
            )
            policy = AlertPolicyService.create(
                session,
                name="Person at front door",
                enabled=True,
                severity="warning",
                match={
                    "camera_ids": [str(camera_id)],
                    "categories": ["object"],
                    "labels": ["person"],
                    "min_confidence": 0.7,
                },
                actions={
                    "notification_target_ids": [str(target.id)],
                    "protect_recording": True,
                    "protect_before_seconds": 10,
                    "protect_after_seconds": 20,
                },
                cooldown_seconds=60,
            )
            session.commit()
            policy_id = policy.id

        started = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

        with database.session() as session:
            event = EventService.upsert_provider_event(
                session,
                item=EventIngest(
                    source="frigate",
                    source_instance_id="frigate-a",
                    source_event_id="event-1",
                    camera_id=camera_id,
                    category="object",
                    label="person",
                    started_at=started,
                    ended_at=started + timedelta(seconds=8),
                    confidence=0.91,
                ),
            ).event

            first = AlertEvaluationService.evaluate_event(
                session,
                event=event,
            )
            assert len(first.alerts) == 1
            assert len(first.delivery_ids) == 1

            retry = AlertEvaluationService.evaluate_event(
                session,
                event=event,
            )
            assert retry.alerts == ()
            assert retry.delivery_ids == ()
            session.commit()

        with database.session() as session:
            alert = session.scalar(
                select(Alert).where(
                    Alert.policy_id == policy_id
                )
            )
            assert alert is not None
            assert alert.severity == "warning"
            assert alert.state == "OPEN"

            delivery = session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.alert_id == alert.id
                )
            )
            assert delivery is not None
            assert delivery.state == "PENDING"
            assert delivery.attempts == 0

            protection = session.scalar(
                select(RecordingProtection).where(
                    RecordingProtection.camera_id == camera_id
                )
            )
            assert protection is not None
            assert protection.started_at == started - timedelta(seconds=10)
            assert protection.ended_at == started + timedelta(seconds=28)

        # A second matching event inside the cooldown does not create an alert.
        with database.session() as session:
            event2 = EventService.upsert_provider_event(
                session,
                item=EventIngest(
                    source="frigate",
                    source_instance_id="frigate-a",
                    source_event_id="event-2",
                    camera_id=camera_id,
                    category="object",
                    label="person",
                    started_at=started + timedelta(seconds=30),
                    ended_at=started + timedelta(seconds=35),
                    confidence=0.95,
                ),
            ).event
            result = AlertEvaluationService.evaluate_event(
                session,
                event=event2,
            )
            assert result.alerts == ()
            session.commit()

        # Outside cooldown it creates a second alert.
        with database.session() as session:
            event3 = EventService.upsert_provider_event(
                session,
                item=EventIngest(
                    source="frigate",
                    source_instance_id="frigate-a",
                    source_event_id="event-3",
                    camera_id=camera_id,
                    category="object",
                    label="person",
                    started_at=started + timedelta(seconds=61),
                    ended_at=started + timedelta(seconds=66),
                    confidence=0.95,
                ),
            ).event
            result = AlertEvaluationService.evaluate_event(
                session,
                event=event3,
            )
            assert len(result.alerts) == 1
            session.commit()

        with database.session() as session:
            assert session.scalar(
                select(func.count()).select_from(Alert)
            ) == 2
    finally:
        database.close()


def test_min_duration_waits_for_event_end_update(tmp_path: Path) -> None:
    settings, database = make_database(tmp_path)
    try:
        camera_id = seed_camera(settings, database)
        with database.session() as session:
            AlertPolicyService.create(
                session,
                name="Long person",
                enabled=True,
                severity="info",
                match={
                    "labels": ["person"],
                    "min_duration_seconds": 5,
                },
                actions={},
                cooldown_seconds=0,
            )
            session.commit()

        start = datetime(2026, 9, 20, 13, 0, tzinfo=UTC)

        with database.session() as session:
            event = EventService.upsert_provider_event(
                session,
                item=EventIngest(
                    source="frigate",
                    source_instance_id="frigate-a",
                    source_event_id="duration-1",
                    camera_id=camera_id,
                    category="object",
                    label="person",
                    started_at=start,
                    ended_at=None,
                ),
            ).event
            assert AlertEvaluationService.evaluate_event(
                session,
                event=event,
            ).alerts == ()
            session.commit()

        with database.session() as session:
            event = EventService.upsert_provider_event(
                session,
                item=EventIngest(
                    source="frigate",
                    source_instance_id="frigate-a",
                    source_event_id="duration-1",
                    camera_id=camera_id,
                    category="object",
                    label="person",
                    started_at=start,
                    ended_at=start + timedelta(seconds=6),
                ),
            ).event
            assert len(
                AlertEvaluationService.evaluate_event(
                    session,
                    event=event,
                ).alerts
            ) == 1
            session.commit()
    finally:
        database.close()
