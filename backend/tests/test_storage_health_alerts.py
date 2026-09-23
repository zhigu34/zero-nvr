from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import uuid

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.alerts.models import Alert
from app.modules.alerts.service import (
    AlertEvaluationService,
    AlertPolicyService,
)
from app.modules.events.models import Event
from app.modules.events.system import SystemEventService


def make_database(tmp_path: Path) -> Database:
    settings = Settings(
        secret_key="storage-health-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'storage-health.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return database


def test_storage_health_transition_creates_and_resolves_policy_alert(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    target_id = uuid.uuid4()
    started = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    try:
        with database.session() as session:
            AlertPolicyService.create(
                session,
                name="Recording storage health",
                enabled=True,
                severity="critical",
                match={
                    "categories": ["storage_health"],
                },
                actions={},
                cooldown_seconds=0,
            )
            transition = (
                SystemEventService.storage_health_transition(
                    session,
                    target_id=target_id,
                    target_name="Local recording",
                    observed_at=started,
                    level="critical",
                    used_percent=96.0,
                    free_bytes=400,
                    total_bytes=10_000,
                )
            )
            assert transition.opened is not None
            assert transition.closed is None
            result = AlertEvaluationService.evaluate_event(
                session,
                event=transition.opened,
            )
            assert len(result.alerts) == 1
            event_id = transition.opened.id
            alert_id = result.alerts[0].id
            session.commit()

        with database.session() as session:
            repeated = (
                SystemEventService.storage_health_transition(
                    session,
                    target_id=target_id,
                    target_name="Local recording",
                    observed_at=started + timedelta(minutes=5),
                    level="critical",
                    used_percent=97.0,
                    free_bytes=300,
                    total_bytes=10_000,
                )
            )
            assert repeated.opened is None
            assert repeated.closed is None
            assert session.scalar(
                select(func.count()).select_from(Event)
            ) == 1
            assert session.scalar(
                select(func.count()).select_from(Alert)
            ) == 1
            session.commit()

        recovered_at = started + timedelta(minutes=10)
        with database.session() as session:
            recovery = (
                SystemEventService.storage_health_transition(
                    session,
                    target_id=target_id,
                    target_name="Local recording",
                    observed_at=recovered_at,
                    level="ok",
                    used_percent=70.0,
                    free_bytes=3_000,
                    total_bytes=10_000,
                )
            )
            assert recovery.opened is None
            assert recovery.closed is not None
            resolved = (
                AlertEvaluationService.resolve_event_alerts(
                    session,
                    event=recovery.closed,
                )
            )
            assert [item.id for item in resolved] == [alert_id]
            session.commit()

        with database.session() as session:
            event = session.get(Event, event_id)
            alert = session.get(Alert, alert_id)
            assert event is not None
            assert event.ended_at == recovered_at
            assert alert is not None
            assert alert.state == "RESOLVED"
            assert alert.resolved_at == recovered_at

        with database.session() as session:
            second = (
                SystemEventService.storage_health_transition(
                    session,
                    target_id=target_id,
                    target_name="Local recording",
                    observed_at=started + timedelta(minutes=20),
                    level="unavailable",
                    error_code="storage_capacity_unavailable",
                )
            )
            assert second.opened is not None
            assert second.opened.id != event_id
            created = AlertEvaluationService.evaluate_event(
                session,
                event=second.opened,
            )
            assert len(created.alerts) == 1
            session.commit()

        with database.session() as session:
            assert session.scalar(
                select(func.count()).select_from(Event)
            ) == 2
            assert session.scalar(
                select(func.count()).select_from(Alert)
            ) == 2
    finally:
        database.close()


def test_storage_health_level_change_closes_previous_incident(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    target_id = uuid.uuid4()
    started = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)
    try:
        with database.session() as session:
            first = SystemEventService.storage_health_transition(
                session,
                target_id=target_id,
                target_name="Local recording",
                observed_at=started,
                level="warning",
            )
            assert first.opened is not None
            first_id = first.opened.id

            changed = SystemEventService.storage_health_transition(
                session,
                target_id=target_id,
                target_name="Local recording",
                observed_at=started + timedelta(minutes=5),
                level="high",
            )
            assert changed.closed is not None
            assert changed.closed.id == first_id
            assert changed.opened is not None
            assert changed.opened.id != first_id
            assert changed.opened.label == "storage_high"
            session.commit()
    finally:
        database.close()
