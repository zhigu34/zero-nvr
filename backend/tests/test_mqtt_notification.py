from __future__ import annotations

import json

import paho.mqtt.client as mqtt
import pytest

from app.integrations.apprise import (
    AppriseAdapter,
    AppriseIntegrationError,
)


class FakePublishInfo:
    def __init__(
        self,
        *,
        rc: int = mqtt.MQTT_ERR_SUCCESS,
        published: bool = True,
    ) -> None:
        self.rc = rc
        self.published = published
        self.wait_timeout = None

    def wait_for_publish(
        self,
        timeout=None,
    ) -> None:
        self.wait_timeout = timeout

    def is_published(self) -> bool:
        return self.published


class FakeMqttClient:
    instances = []

    def __init__(
        self,
        callback_api_version,
        *,
        client_id,
        protocol,
    ) -> None:
        self.callback_api_version = (
            callback_api_version
        )
        self.client_id = client_id
        self.protocol = protocol
        self.username = None
        self.password = None
        self.tls = False
        self.connected = None
        self.loop_started = False
        self.disconnected = False
        self.loop_stopped = False
        self.published = None
        self.info = FakePublishInfo()
        self.__class__.instances.append(self)

    def username_pw_set(
        self,
        username,
        password,
    ) -> None:
        self.username = username
        self.password = password

    def tls_set(self) -> None:
        self.tls = True

    def connect(
        self,
        host,
        port,
        *,
        keepalive,
    ) -> None:
        self.connected = (
            host,
            port,
            keepalive,
        )

    def loop_start(self) -> None:
        self.loop_started = True

    def publish(
        self,
        topic,
        *,
        payload,
        qos,
        retain,
    ):
        self.published = {
            "topic": topic,
            "payload": payload,
            "qos": qos,
            "retain": retain,
        }
        return self.info

    def disconnect(self) -> None:
        self.disconnected = True

    def loop_stop(self) -> None:
        self.loop_stopped = True


def test_native_mqtt_notification_uses_paho_v2_and_json_payload() -> None:
    FakeMqttClient.instances = []
    adapter = AppriseAdapter(
        url=(
            "mqtts://user:super-secret@"
            "broker.example:8883/zero-nvr/alerts"
            "?qos=1&retain=yes&client_id=zero-nvr-test"
        ),
        mqtt_client_factory=FakeMqttClient,
    )

    adapter.notify(
        title="Camera offline",
        body="Front Door is offline",
        notify_type="warning",
    )

    assert len(FakeMqttClient.instances) == 1
    client = FakeMqttClient.instances[0]
    assert (
        client.callback_api_version
        == mqtt.CallbackAPIVersion.VERSION2
    )
    assert client.protocol == mqtt.MQTTv311
    assert client.client_id == "zero-nvr-test"
    assert client.username == "user"
    assert client.password == "super-secret"
    assert client.tls is True
    assert client.connected == (
        "broker.example",
        8883,
        30,
    )
    assert client.loop_started is True
    assert client.disconnected is True
    assert client.loop_stopped is True

    assert client.published is not None
    assert client.published["topic"] == (
        "zero-nvr/alerts"
    )
    assert client.published["qos"] == 1
    assert client.published["retain"] is True
    payload = json.loads(
        client.published["payload"]
    )
    assert payload == {
        "source": "zero-nvr",
        "type": "warning",
        "title": "Camera offline",
        "body": "Front Door is offline",
    }
    assert client.info.wait_timeout == 10.0


@pytest.mark.parametrize(
    "url",
    [
        "mqtt://broker.example",
        "mqtt://broker.example/topic?qos=9",
        "mqtt://broker.example/topic?retain=maybe",
        "mqtt://broker.example/topic?unknown=1",
    ],
)
def test_mqtt_notification_rejects_invalid_urls(
    url: str,
) -> None:
    with pytest.raises(
        AppriseIntegrationError
    ) as captured:
        AppriseAdapter(
            url=url,
            mqtt_client_factory=FakeMqttClient,
        )
    assert captured.value.code == (
        "notification_url_invalid"
    )


def test_mqtt_delivery_failure_never_echoes_credentials() -> None:
    secret_url = (
        "mqtt://operator:very-secret@"
        "broker.example/alerts"
    )

    class FailingClient(FakeMqttClient):
        def connect(
            self,
            host,
            port,
            *,
            keepalive,
        ) -> None:
            raise OSError(
                "broker refused connection"
            )

    adapter = AppriseAdapter(
        url=secret_url,
        mqtt_client_factory=FailingClient,
    )
    with pytest.raises(
        AppriseIntegrationError
    ) as captured:
        adapter.notify(
            title="Test",
            body="Body",
            notify_type="info",
        )

    assert captured.value.code == (
        "notification_delivery_failed"
    )
    message = str(captured.value)
    assert "very-secret" not in message
    assert "operator" not in message
    assert "broker.example" not in message
