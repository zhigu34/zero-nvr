from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import Base, Database
from app.integrations.apprise import AppriseIntegrationError
from app.modules.alerts.models import Alert, AlertPolicy
from app.modules.auth.models import SecretRecord
from app.modules.cameras.service import CameraService
from app.modules.events.models import Event
from app.modules.notifications.delivery import NotificationDeliveryService
from app.modules.notifications.models import NotificationDelivery
from app.modules.notifications.service import NotificationTargetService


SECRET_URL = "json://user:super-secret@example.invalid/token"


def make_database(tmp_path: Path):
    settings = Settings(
        secret_key="notification-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'notifications.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def seed_delivery(settings: Settings, database: Database):
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
        target = NotificationTargetService(settings).create(
            session,
            name="Ops",
            enabled=True,
            config={"notify_type": "warning"},
            url=SECRET_URL,
        )
        policy = AlertPolicy(
            name="Test Policy",
            enabled=True,
            severity="warning",
            match_json={},
            action_json={},
            cooldown_seconds=0,
        )
        session.add(policy)
        session.flush()
        event = Event(
            source="system",
            category="test",
            camera_id=camera.id,
            started_at=datetime.now(UTC),
            metadata_json={},
        )
        session.add(event)
        session.flush()
        alert = Alert(
            policy_id=policy.id,
            event_id=event.id,
            camera_id=camera.id,
            severity="warning",
            title="Test alert",
            message="Test body",
            state="OPEN",
        )
        session.add(alert)
        session.flush()
        delivery = NotificationDelivery(
            alert_id=alert.id,
            notification_target_id=target.id,
            purpose="alert",
            state="PENDING",
            attempt_count=0,
            title=alert.title,
            body=alert.message or alert.title,
            correlation_id=str(alert.id),
        )
        session.add(delivery)
        session.commit()
        return target.id, delivery.id


def test_notification_url_is_encrypted_and_resolvable(tmp_path: Path) -> None:
    settings, database = make_database(tmp_path)
    try:
        target_id, _delivery_id = seed_delivery(
            settings,
            database,
        )

        with database.session() as session:
            target = NotificationTargetService.get(
                session,
                target_id,
            )
            resolved = NotificationTargetService(
                settings
            ).resolve(
                session,
                target=target,
            )
            assert resolved.url == SECRET_URL

            secret = session.get(
                SecretRecord,
                target.secret_ref,
            )
            assert secret is not None
            assert b"super-secret" not in secret.encrypted_payload
            assert b"example.invalid" not in secret.encrypted_payload
    finally:
        database.close()


class SuccessAdapter:
    calls = []

    def __init__(self, *, url: str) -> None:
        self.url = url

    def notify(self, *, title: str, body: str, notify_type: str) -> None:
        self.calls.append((self.url, title, body, notify_type))


class FailingAdapter:
    def __init__(self, *, url: str) -> None:
        assert url == SECRET_URL

    def notify(self, *, title: str, body: str, notify_type: str) -> None:
        raise AppriseIntegrationError(
            "notification_delivery_failed",
            "Notification delivery failed.",
        )


def test_delivery_success_and_retry_after_failure(tmp_path: Path) -> None:
    settings, database = make_database(tmp_path)
    try:
        _target_id, delivery_id = seed_delivery(
            settings,
            database,
        )

        with pytest.raises(AppriseIntegrationError) as captured:
            NotificationDeliveryService(
                settings,
                adapter_factory=FailingAdapter,
            ).execute(
                database,
                delivery_id=delivery_id,
            )
        assert SECRET_URL not in str(captured.value)

        with database.session() as session:
            failed = session.get(
                NotificationDelivery,
                delivery_id,
            )
            assert failed is not None
            assert failed.state == "FAILED"
            assert failed.attempt_count == 1
            assert (
                failed.last_error_code
                == "notification_delivery_failed"
            )

        SuccessAdapter.calls = []
        result = NotificationDeliveryService(
            settings,
            adapter_factory=SuccessAdapter,
        ).execute(
            database,
            delivery_id=delivery_id,
        )
        assert result.state == "SENT"
        assert result.delivered is True
        assert len(SuccessAdapter.calls) == 1
        assert SuccessAdapter.calls[0][0] == SECRET_URL

        with database.session() as session:
            sent = session.get(
                NotificationDelivery,
                delivery_id,
            )
            assert sent is not None
            assert sent.state == "SENT"
            assert sent.attempt_count == 2
            assert sent.sent_at is not None

        # Already-sent task replay is idempotent.
        replay = NotificationDeliveryService(
            settings,
            adapter_factory=FailingAdapter,
        ).execute(
            database,
            delivery_id=delivery_id,
        )
        assert replay.state == "SENT"
        assert replay.delivered is False
    finally:
        database.close()



class PermanentFailingAdapter:
    def __init__(self, *, url: str) -> None:
        assert url == SECRET_URL

    def notify(
        self,
        *,
        title: str,
        body: str,
        notify_type: str,
    ) -> None:
        raise AppriseIntegrationError(
            "notification_url_invalid",
            "Notification target URL is invalid.",
            status_code=400,
            category="permanent",
        )


class RateLimitedAdapter:
    def __init__(self, *, url: str) -> None:
        assert url == SECRET_URL

    def notify(
        self,
        *,
        title: str,
        body: str,
        notify_type: str,
    ) -> None:
        raise AppriseIntegrationError(
            "notification_rate_limited",
            "Notification delivery failed.",
            status_code=429,
            category="rate_limited",
        )


def test_permanent_notification_failure_does_not_raise_for_huey_retry(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        _target_id, delivery_id = seed_delivery(
            settings,
            database,
        )

        result = NotificationDeliveryService(
            settings,
            adapter_factory=PermanentFailingAdapter,
        ).execute(
            database,
            delivery_id=delivery_id,
        )
        assert result.state == "FAILED"
        assert result.delivered is False

        with database.session() as session:
            failed = session.get(
                NotificationDelivery,
                delivery_id,
            )
            assert failed is not None
            assert failed.attempt_count == 1
            assert (
                failed.last_error_code
                == "notification_url_invalid"
            )
    finally:
        database.close()


def test_rate_limited_notification_failure_remains_retryable(
    tmp_path: Path,
) -> None:
    settings, database = make_database(tmp_path)
    try:
        _target_id, delivery_id = seed_delivery(
            settings,
            database,
        )

        with pytest.raises(
            AppriseIntegrationError
        ) as captured:
            NotificationDeliveryService(
                settings,
                adapter_factory=RateLimitedAdapter,
            ).execute(
                database,
                delivery_id=delivery_id,
            )
        assert (
            captured.value.category
            == "rate_limited"
        )
        assert captured.value.status_code == 429
    finally:
        database.close()
