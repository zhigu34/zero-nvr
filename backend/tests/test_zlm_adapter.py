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


def test_media_probe_returns_only_matching_stream_tracks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/getMediaList")
        body = form(request)
        assert body["app"] == ["zero-nvr"]
        assert body["stream"] == ["profile-target"]
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [
                    {
                        "stream": "profile-other",
                        "tracks": [],
                    },
                    {
                        "stream": "profile-target",
                        "tracks": [
                            {
                                "codec_id_name": "H264",
                                "ready": True,
                                "width": 1280,
                                "height": 720,
                                "fps": 15,
                            }
                        ],
                    },
                ],
            },
        )

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
    ) as adapter:
        probe = adapter.media_probe(
            app="zero-nvr",
            stream="profile-target",
        )

    assert probe is not None
    assert probe.stream == "profile-target"
    assert probe.video is not None
    assert probe.video.codec == "h264"
    assert probe.video.ready is True
    assert probe.video.width == 1280
    assert probe.video.height == 720
    assert probe.video.fps == 15


def test_wait_media_online_polls_until_registered() -> None:
    online = [False, False, True]
    clock = [0.0]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/isMediaOnline")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "online": online.pop(0),
            },
        )

    def monotonic() -> float:
        return clock[0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
        monotonic=monotonic,
        sleep=sleep,
        poll_interval_seconds=0.25,
    ) as adapter:
        assert adapter.wait_media_online(
            app="zero-nvr",
            stream="profile-live",
            timeout_seconds=1.0,
        ) is True

    assert len(requests) == 3
    assert clock[0] == pytest.approx(0.5)


def test_wait_video_ready_polls_until_video_track_is_ready() -> None:
    probes = [
        [],
        [
            {
                "stream": "profile-live",
                "tracks": [
                    {
                        "codec_id_name": "H264",
                        "ready": False,
                        "width": 1280,
                        "height": 720,
                    }
                ],
            }
        ],
        [
            {
                "stream": "profile-live",
                "tracks": [
                    {
                        "codec_id_name": "H264",
                        "ready": True,
                        "width": 1280,
                        "height": 720,
                    }
                ],
            }
        ],
    ]
    clock = [0.0]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/getMediaList")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": probes.pop(0),
            },
        )

    def monotonic() -> float:
        return clock[0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
        monotonic=monotonic,
        sleep=sleep,
        poll_interval_seconds=0.25,
    ) as adapter:
        assert adapter.wait_video_ready(
            app="zero-nvr",
            stream="profile-live",
            timeout_seconds=1.0,
        ) is True

    assert len(requests) == 3
    assert clock[0] == pytest.approx(0.5)


def test_add_stream_proxy_forwards_auto_close_policy() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/addStreamProxy")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"key": "__defaultVhost__/zero-nvr/profile-live"},
            },
        )

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
    ) as adapter:
        adapter.add_stream_proxy(
            app="zero-nvr",
            stream="profile-live",
            source_url=SOURCE_URL,
            enable_hls=True,
            auto_close=True,
            mp4_as_player=True,
        )

    assert len(requests) == 1
    body = form(requests[0])
    assert body["auto_close"] == ["1"]
    assert body["mp4_as_player"] == ["1"]
    assert body["enable_hls"] == ["1"]


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



def test_mp4_recorder_control_uses_zlm_native_api() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        api = request.url.path.rsplit("/", 1)[-1]
        if api == "startRecord":
            return httpx.Response(
                200,
                json={"code": 0, "result": True},
            )
        if api == "isRecording":
            return httpx.Response(
                200,
                json={"code": 0, "status": True},
            )
        if api == "stopRecord":
            return httpx.Response(
                200,
                json={"code": 0, "result": True},
            )
        raise AssertionError(api)

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
    ) as adapter:
        assert adapter.start_mp4_recording(
            app="zero-nvr",
            stream="profile-abc",
            customized_path="/recordings",
            max_second=300,
        ) is True
        assert adapter.is_mp4_recording(
            app="zero-nvr",
            stream="profile-abc",
        ) is True
        assert adapter.stop_mp4_recording(
            app="zero-nvr",
            stream="profile-abc",
        ) is True

    assert [
        request.url.path.rsplit("/", 1)[-1]
        for request in requests
    ] == [
        "startRecord",
        "isRecording",
        "stopRecord",
    ]

    for request in requests:
        assert not request.url.query
        body = form(request)
        assert body["secret"] == [ZLM_SECRET]
        assert body["type"] == ["1"]
        assert body["vhost"] == ["__defaultVhost__"]
        assert body["app"] == ["zero-nvr"]
        assert body["stream"] == ["profile-abc"]

    start_body = form(requests[0])
    assert start_body["customized_path"] == ["/recordings"]
    assert start_body["max_second"] == ["300"]



def test_load_mp4_file_uses_native_zlm_vod_api() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/loadMP4File")
        return httpx.Response(
            200,
            json={"code": 0, "result": True},
        )

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
    ) as adapter:
        assert adapter.load_mp4_file(
            app="zero-nvr-vod",
            stream="segment-test",
            file_path="/recordings/record/zero-nvr/test.mp4",
            seek_ms=12345,
            speed=1.0,
        )

    assert len(requests) == 1
    assert not requests[0].url.query
    body = form(requests[0])
    assert body["secret"] == [ZLM_SECRET]
    assert body["vhost"] == ["__defaultVhost__"]
    assert body["app"] == ["zero-nvr-vod"]
    assert body["stream"] == ["segment-test"]
    assert body["file_path"] == [
        "/recordings/record/zero-nvr/test.mp4"
    ]
    assert body["seek_ms"] == ["12345"]
    assert body["enable_fmp4"] == ["1"]
    assert body["enable_rtsp"] == ["1"]
    assert body["auto_close"] == ["1"]



def test_snapshot_posts_sensitive_inputs_and_returns_jpeg() -> None:
    requests: list[httpx.Request] = []
    internal_url = "rtsp://zlmediakit:554/zero-nvr/profile-test"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/getSnap")
        return httpx.Response(
            200,
            content=b"\xff\xd8fake-jpeg\xff\xd9",
            headers={"content-type": "image/jpeg"},
        )

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
    ) as adapter:
        content, content_type = adapter.snapshot(
            source_url=internal_url,
            timeout_seconds=7,
            expire_seconds=2,
        )

    assert content.startswith(b"\xff\xd8")
    assert content_type == "image/jpeg"
    assert len(requests) == 1
    request = requests[0]
    assert not request.url.query
    body = form(request)
    assert body["secret"] == [ZLM_SECRET]
    assert body["url"] == [internal_url]
    assert body["timeout_sec"] == ["7"]
    assert body["expire_sec"] == ["2"]


def test_snapshot_rejects_non_image_response_without_echoing_url() -> None:
    internal_url = "rtsp://zlmediakit:554/zero-nvr/profile-secret"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": -1,
                "msg": f"failed to open {internal_url}",
            },
        )

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
    ) as adapter:
        with pytest.raises(ZlmIntegrationError) as captured:
            adapter.snapshot(source_url=internal_url)

    assert captured.value.code == "zlm_snapshot_failed"
    assert internal_url not in str(captured.value)



def test_whep_play_and_cleanup_use_standard_session_contract() -> None:
    requests: list[httpx.Request] = []
    offer = "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\n"
    answer = "v=0\r\no=- 2 2 IN IP4 127.0.0.1\r\n"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/whep"):
            assert request.extensions["timeout"] == {
                "connect": 2.0,
                "read": None,
                "write": 2.0,
                "pool": 2.0,
            }
            return httpx.Response(
                201,
                text=answer,
                headers={
                    "content-type": "application/sdp",
                    "location": (
                        "/index/api/delete_webrtc"
                        "?id=rtc-session-1"
                        "&token=rtc-delete-token"
                    ),
                },
            )
        if request.url.path.endswith("/delete_webrtc"):
            return httpx.Response(
                200,
                json={"code": 0},
            )
        raise AssertionError(request.url.path)

    with ZlmAdapter(
        settings(),
        transport=httpx.MockTransport(handler),
    ) as adapter:
        session = adapter.whep_play(
            app="zero-nvr",
            stream="profile-abc",
            offer_sdp=offer,
            playback_params={
                "zn_exp": "1234567890",
                "zn_sig": "play-signature",
            },
            candidate_udp="192.0.2.10:8000",
            candidate_tcp="192.0.2.10:8000",
        )
        assert session.answer_sdp == answer
        assert session.session_id == "rtc-session-1"
        assert session.session_token == "rtc-delete-token"

        adapter.delete_webrtc(
            session_id=session.session_id,
            session_token=session.session_token,
        )

    assert len(requests) == 2

    create_request = requests[0]
    assert create_request.method == "POST"
    assert create_request.headers["content-type"].startswith(
        "application/sdp"
    )
    assert create_request.content.decode("utf-8") == offer
    query = parse_qs(
        create_request.url.query.decode("utf-8")
    )
    assert query["app"] == ["zero-nvr"]
    assert query["stream"] == ["profile-abc"]
    assert query["zn_exp"] == ["1234567890"]
    assert query["zn_sig"] == ["play-signature"]
    assert query["cand_udp"] == ["192.0.2.10:8000"]
    assert query["cand_tcp"] == ["192.0.2.10:8000"]
    assert "secret" not in query

    delete_request = requests[1]
    assert delete_request.method == "DELETE"
    delete_query = parse_qs(
        delete_request.url.query.decode("utf-8")
    )
    assert delete_query == {
        "id": ["rtc-session-1"],
        "token": ["rtc-delete-token"],
    }
