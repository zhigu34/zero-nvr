from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

import paho.mqtt.client as mqtt
from sqlalchemy import inspect

from app.core.config import Settings
from app.core.db import Database
from app.modules.events.frigate import FrigateEventIngestService
from app.modules.recordings.dispatcher import RecordingTaskDispatcher
from app.modules.system.frigate import (
    FrigateProviderConfig,
    FrigateProviderSettingsService,
)


@dataclass(frozen=True, slots=True)
class FrigateMqttStatus:
    enabled: bool
    connected: bool
    topic: str | None
    last_error: str | None


class FrigateMqttRuntime:
    """In-process low-latency Frigate MQTT ingest.

    HTTP backfill remains the durable recovery path. No raw MQTT event table or
    dedicated single-purpose container is introduced.
    """

    def __init__(
        self,
        settings: Settings,
        database: Database,
        *,
        logger: logging.Logger,
        recording_tasks: RecordingTaskDispatcher,
        client_factory: Callable[..., Any] = mqtt.Client,
    ) -> None:
        self.settings = settings
        self.database = database
        self.logger = logger
        self.recording_tasks = recording_tasks
        self._client_factory = client_factory
        self._lock = threading.Lock()
        self._client: Any | None = None
        self._config: FrigateProviderConfig | None = None
        self._connected = False
        self._last_error: str | None = None
        self._topic: str | None = None

    def status(self) -> FrigateMqttStatus:
        with self._lock:
            config = self._config
            return FrigateMqttStatus(
                enabled=bool(
                    config is not None
                    and config.enabled
                    and config.mqtt_enabled
                ),
                connected=self._connected,
                topic=self._topic,
                last_error=self._last_error,
            )

    def _load_config(self) -> FrigateProviderConfig | None:
        # Optional integrations must not make the API unbootable before the
        # schema migration/bootstrap step has created product setting tables.
        if not inspect(self.database.engine).has_table(
            "system_settings"
        ):
            return None

        service = FrigateProviderSettingsService(
            self.settings
        )
        with self.database.session() as session:
            config = service.get(session)
            session.commit()
            return config

    def start(self) -> None:
        self.reconfigure()

    def stop(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
            self._config = None
            self._topic = None
            self._connected = False

        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop()
            except Exception:
                pass

    def reconfigure(self) -> None:
        config = self._load_config()

        with self._lock:
            old = self._client
            self._client = None
            self._connected = False
            self._last_error = None
            self._topic = None
            self._config = config

        if old is not None:
            try:
                old.disconnect()
            except Exception:
                pass
            try:
                old.loop_stop()
            except Exception:
                pass

        if (
            config is None
            or not config.enabled
            or not config.mqtt_enabled
        ):
            return

        assert config.mqtt_host is not None
        topic = f"{config.mqtt_topic_prefix}/events"
        client_id = (
            "zero-nvr-frigate-"
            f"{config.instance_id[:16]}"
        )

        client = self._client_factory(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=False,
            protocol=mqtt.MQTTv311,
        )
        credentials = config.credentials
        if credentials.mqtt_username is not None:
            client.username_pw_set(
                credentials.mqtt_username,
                credentials.mqtt_password,
            )
        if config.mqtt_tls:
            client.tls_set()

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        with self._lock:
            self._client = client
            self._topic = topic

        try:
            client.connect_async(
                config.mqtt_host,
                config.mqtt_port,
                keepalive=60,
            )
            client.loop_start()
        except Exception:
            with self._lock:
                self._last_error = "mqtt_start_failed"
                self._client = None
                self._connected = False
            try:
                client.loop_stop()
            except Exception:
                pass
            raise

    def _on_connect(
        self,
        client,
        _userdata,
        _flags,
        reason_code,
        _properties,
    ) -> None:
        try:
            failed = bool(
                getattr(reason_code, "is_failure", False)
            )
        except Exception:
            failed = True

        if failed:
            with self._lock:
                self._connected = False
                self._last_error = "mqtt_connect_failed"
            return

        with self._lock:
            topic = self._topic
            self._connected = True
            self._last_error = None

        if topic is not None:
            client.subscribe(topic, qos=1)

    def _on_disconnect(
        self,
        _client,
        _userdata,
        _disconnect_flags,
        reason_code,
        _properties,
    ) -> None:
        with self._lock:
            self._connected = False
            if bool(
                getattr(reason_code, "is_failure", False)
            ):
                self._last_error = "mqtt_disconnected"

    def _on_message(
        self,
        _client,
        _userdata,
        message,
    ) -> None:
        with self._lock:
            config = self._config
            topic = self._topic

        if (
            config is None
            or topic is None
            or message.topic != topic
        ):
            return

        try:
            payload = json.loads(
                bytes(message.payload).decode("utf-8")
            )
            if not isinstance(payload, dict):
                return
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.logger.warning(
                "ignored invalid Frigate MQTT event payload"
            )
            return

        try:
            with self.database.session() as session:
                result = FrigateEventIngestService.mqtt(
                    session,
                    config=config,
                    payload=payload,
                )
                session.commit()

            if (
                result.trigger_changed
                and result.trigger_camera_id is not None
            ):
                self.recording_tasks.reconcile_camera(
                    result.trigger_camera_id
                )
        except Exception:
            # Provider payload and credentials are intentionally omitted.
            self.logger.warning(
                "Frigate MQTT event ingest failed"
            )
