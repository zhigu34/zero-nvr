from __future__ import annotations

import json
import uuid
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from apprise import Apprise, NotifyType
import paho.mqtt.client as mqtt


class AppriseIntegrationError(RuntimeError):
    """Sanitized notification delivery failure.

    Never expose notification URLs in raised errors: they commonly embed
    credentials, tokens, recipients, or webhook secrets.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
        category: str = "transient",
    ) -> None:
        super().__init__(message)
        if category not in {
            "transient",
            "permanent",
            "rate_limited",
        }:
            raise ValueError(
                "notification error category is invalid"
            )
        self.code = code
        self.status_code = status_code
        self.category = category


_NOTIFY_TYPES = {
    "info": NotifyType.INFO,
    "success": NotifyType.SUCCESS,
    "warning": NotifyType.WARNING,
    "failure": NotifyType.FAILURE,
}


class _MqttNotificationTarget:
    """Native paho-mqtt 2.x publisher for MQTT notification URLs.

    Apprise's MQTT plugin still depends on paho-mqtt <2 while zero-nvr uses
    paho-mqtt 2.x for Frigate ingest. Routing only mqtt:// and mqtts:// here
    keeps one MQTT runtime dependency without weakening the Frigate client.
    """

    def __init__(
        self,
        *,
        url: str,
        client_factory: Callable[..., Any],
    ) -> None:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "Notification target URL is invalid.",
                status_code=400,
                category="permanent",
            ) from exc

        scheme = parsed.scheme.lower()
        if (
            scheme not in {"mqtt", "mqtts"}
            or not parsed.hostname
            or parsed.fragment
        ):
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "MQTT notification target URL is invalid.",
                status_code=400,
                category="permanent",
            )

        raw_topic = (
            parsed.path[1:]
            if parsed.path.startswith("/")
            else parsed.path
        )
        topic = unquote(raw_topic)
        if not topic or "\x00" in topic:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "MQTT notification topic is invalid.",
                status_code=400,
                category="permanent",
            )

        query = parse_qs(
            parsed.query,
            keep_blank_values=True,
        )
        unsupported = set(query) - {
            "qos",
            "retain",
            "client_id",
        }
        if unsupported or any(
            len(values) != 1
            for values in query.values()
        ):
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "MQTT notification target contains unsupported parameters.",
                status_code=400,
                category="permanent",
            )

        try:
            qos = int(
                query.get("qos", ["0"])[0]
            )
        except ValueError as exc:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "MQTT notification QoS is invalid.",
                status_code=400,
                category="permanent",
            ) from exc
        if qos not in {0, 1, 2}:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "MQTT notification QoS is invalid.",
                status_code=400,
                category="permanent",
            )

        retain_raw = (
            query.get("retain", ["no"])[0]
            .strip()
            .lower()
        )
        if retain_raw in {"1", "true", "yes", "on"}:
            retain = True
        elif retain_raw in {
            "0",
            "false",
            "no",
            "off",
            "",
        }:
            retain = False
        else:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "MQTT notification retain flag is invalid.",
                status_code=400,
                category="permanent",
            )

        self.host = parsed.hostname
        self.port = (
            port
            if port is not None
            else (8883 if scheme == "mqtts" else 1883)
        )
        self.topic = topic
        self.username = (
            unquote(parsed.username)
            if parsed.username is not None
            else None
        )
        self.password = (
            unquote(parsed.password)
            if parsed.password is not None
            else None
        )
        self.qos = qos
        self.retain = retain
        configured_client_id = (
            query.get("client_id", [""])[0].strip()
        )
        self.client_id = (
            configured_client_id[:128]
            if configured_client_id
            else (
                "zero-nvr-notify-"
                + uuid.uuid4().hex[:16]
            )
        )
        self.secure = scheme == "mqtts"
        self._client_factory = client_factory

    def notify(
        self,
        *,
        title: str,
        body: str,
        notify_type: str,
    ) -> None:
        client = None
        loop_started = False
        try:
            client = self._client_factory(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.client_id,
                protocol=mqtt.MQTTv311,
            )
            if self.username is not None:
                client.username_pw_set(
                    self.username,
                    self.password,
                )
            if self.secure:
                client.tls_set()

            client.connect(
                self.host,
                self.port,
                keepalive=30,
            )
            client.loop_start()
            loop_started = True

            payload = json.dumps(
                {
                    "source": "zero-nvr",
                    "type": notify_type,
                    "title": title,
                    "body": body,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            result = client.publish(
                self.topic,
                payload=payload,
                qos=self.qos,
                retain=self.retain,
            )
            if (
                getattr(result, "rc", None)
                != mqtt.MQTT_ERR_SUCCESS
            ):
                raise RuntimeError(
                    "MQTT publish was rejected"
                )

            result.wait_for_publish(
                timeout=10.0
            )
            is_published = getattr(
                result,
                "is_published",
                None,
            )
            if (
                callable(is_published)
                and not is_published()
            ):
                raise RuntimeError(
                    "MQTT publish timed out"
                )
        except AppriseIntegrationError:
            raise
        except Exception as exc:
            status_code = getattr(
                exc,
                "status_code",
                None,
            )
            if status_code is None:
                response = getattr(
                    exc,
                    "response",
                    None,
                )
                status_code = getattr(
                    response,
                    "status_code",
                    None,
                )
            raise AppriseIntegrationError(
                (
                    "notification_rate_limited"
                    if status_code == 429
                    else "notification_delivery_failed"
                ),
                "Notification delivery failed.",
                status_code=(
                    429
                    if status_code == 429
                    else 502
                ),
                category=(
                    "rate_limited"
                    if status_code == 429
                    else "transient"
                ),
            ) from exc
        finally:
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass
                if loop_started:
                    try:
                        client.loop_stop()
                    except Exception:
                        pass


class AppriseAdapter:
    def __init__(
        self,
        *,
        url: str,
        apprise_factory: Callable[[], Any] = Apprise,
        mqtt_client_factory: Callable[..., Any] = mqtt.Client,
    ) -> None:
        normalized = url.strip()
        if not normalized:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "Notification target URL is invalid.",
                status_code=400,
            )

        scheme = urlsplit(
            normalized
        ).scheme.lower()
        self._mqtt_target: (
            _MqttNotificationTarget | None
        ) = None
        self._apprise: Any | None = None

        if scheme in {"mqtt", "mqtts"}:
            self._mqtt_target = (
                _MqttNotificationTarget(
                    url=normalized,
                    client_factory=mqtt_client_factory,
                )
            )
            return

        self._apprise = apprise_factory()
        try:
            added = self._apprise.add(normalized)
        except Exception as exc:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "Notification target URL is invalid.",
                status_code=400,
                category="permanent",
            ) from exc

        if not added:
            raise AppriseIntegrationError(
                "notification_url_invalid",
                "Notification target URL is invalid.",
                status_code=400,
                category="permanent",
            )

    def notify(
        self,
        *,
        title: str,
        body: str,
        notify_type: str = "info",
    ) -> None:
        apprise_type = _NOTIFY_TYPES.get(notify_type)
        if apprise_type is None:
            raise AppriseIntegrationError(
                "notification_type_invalid",
                "Notification type is invalid.",
                status_code=400,
                category="permanent",
            )

        if self._mqtt_target is not None:
            self._mqtt_target.notify(
                title=title,
                body=body,
                notify_type=notify_type,
            )
            return

        assert self._apprise is not None
        try:
            delivered = self._apprise.notify(
                body=body,
                title=title,
                notify_type=apprise_type,
            )
        except Exception as exc:
            status_code = getattr(
                exc,
                "status_code",
                None,
            )
            if status_code is None:
                response = getattr(
                    exc,
                    "response",
                    None,
                )
                status_code = getattr(
                    response,
                    "status_code",
                    None,
                )
            raise AppriseIntegrationError(
                (
                    "notification_rate_limited"
                    if status_code == 429
                    else "notification_delivery_failed"
                ),
                "Notification delivery failed.",
                status_code=(
                    429
                    if status_code == 429
                    else 502
                ),
                category=(
                    "rate_limited"
                    if status_code == 429
                    else "transient"
                ),
            ) from exc

        if delivered is not True:
            raise AppriseIntegrationError(
                "notification_delivery_failed",
                "Notification delivery failed.",
            )
