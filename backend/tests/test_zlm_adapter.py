from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.zlm import ZlmAdapter, ZlmIntegrationError


SOURCE_URL = "rtsp://alice:camera-password@10.0.0.8/live?token=source-token"
ZLM_SECRET = "zlm-api-secret-value"


def settings(**overrides):
    values = {
        "secret_key": "z" * 32,
        "zlm_base_url": "http://zlmediakit",
        "zlm_api_secret": SecretStr(ZLM_SECRET),
        "zlm_timeout_seconds": 2.0,
        "zlm_probe_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return Settings(**values)


def form(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode("utf-8"), keep_blank_values=True)


def test_probe_keeps_sensitive_values_out_of_url_and_filters_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        api = request.url.path.rsplit("/", 1)[-1]

        if api == "addStreamProxy":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"key": "probe-key"}},
            )
        if api == "getMediaList":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [
                        {
                            "schema": "rtsp",
                            "stream": "probe-test",
                            "originUrl": SOURCE_URL,
                            "tracks": [
                                {
                                    "codec_id_name": "H264",
                                    "ready": True,
                                    "width": 1920,
                                    "height": 1080,
                                    "fps": 25,
                                    "gop_interval_ms": 2000,
                                },
                                {
                                    "codec_id_name": "AAC",
                                    "ready": True,
                                    "sample_rate": 48000,
                                    "channels": 2,
                                },
                            ],
                        }
                    ],
                },
            )
        if api == "delStreamProxy":
            return httpx.Response(200, json={"code": 0})
        raise AssertionError(f"unexpected API: {api}")

    adapter = ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    try:
        result = adapter.probe_rtsp_source(SOURCE_URL)
    finally:
        adapter.close()

    assert result.video is not None
    assert result.video.codec == "h264"
    assert result.video.width == 1920
    assert result.video.height == 1080
    assert result.video.fps == 25
    assert result.video.gop_seconds == 2.0
    assert result.audio is not None
    assert result.audio.codec == "aac"
    assert result.audio.sample_rate == 48000
    assert result.audio.channels == 2

    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "addStreamProxy",
        "getMediaList",
        "delStreamProxy",
    ]

    for request in requests:
        assert not request.url.query
        assert SOURCE_URL not in str(request.url)
        assert ZLM_SECRET not in str(request.url)

    add_form = form(requests[0])
    assert add_form["secret"] == [ZLM_SECRET]
    assert add_form["url"] == [SOURCE_URL]

    # The ZLM response deliberately contained originUrl with credentials. The
    # typed result exposes only the allow-listed track metadata.
    assert SOURCE_URL not in repr(result)


def test_zlm_error_does_not_echo_sensitive_source_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": -1,
                "msg": f"failed to open {SOURCE_URL}",
            },
        )

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
    ) as adapter:
        with pytest.raises(ZlmIntegrationError) as captured:
            adapter.add_stream_proxy(
                app="zero-nvr-probe",
                stream="probe-error",
                source_url=SOURCE_URL,
            )

    text = str(captured.value)
    assert SOURCE_URL not in text
    assert "camera-password" not in text
    assert "source-token" not in text
    assert captured.value.code == "zlm_operation_failed"


def test_probe_timeout_still_deletes_temporary_proxy() -> None:
    apis: list[str] = []
    clock = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        api = request.url.path.rsplit("/", 1)[-1]
        apis.append(api)
        if api == "addStreamProxy":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"key": "timeout-key"}},
            )
        if api == "getMediaList":
            return httpx.Response(200, json={"code": 0, "data": []})
        if api == "delStreamProxy":
            return httpx.Response(200, json={"code": 0})
        raise AssertionError(api)

    def monotonic() -> float:
        return clock[0]

    def sleep(seconds: float) -> None:
        clock[0] += max(seconds, 0.25)

    adapter = ZlmAdapter(
        settings(zlm_probe_timeout_seconds=0.5),
        transport=httpx.MockTransport(handler),
        monotonic=monotonic,
        sleep=sleep,
        poll_interval_seconds=0.25,
    )
    try:
        with pytest.raises(ZlmIntegrationError) as captured:
            adapter.probe_rtsp_source(SOURCE_URL)
    finally:
        adapter.close()

    assert captured.value.code == "camera_stream_probe_timeout"
    assert apis[0] == "addStreamProxy"
    assert "getMediaList" in apis
    assert apis[-1] == "delStreamProxy"


def test_missing_zlm_secret_is_explicit_and_sanitized() -> None:
    adapter = ZlmAdapter(
        settings(zlm_api_secret=None),
        transport=httpx.MockTransport(
            lambda _request: pytest.fail("HTTP request should not occur")
        ),
    )
    try:
        with pytest.raises(ZlmIntegrationError) as captured:
            adapter.version()
    finally:
        adapter.close()

    assert captured.value.code == "zlm_not_configured"
    assert captured.value.status_code == 503
