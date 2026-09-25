from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.media_proxy import router


class FakeUpstream:
    status_code = 206
    headers = {
        "content-type": "application/vnd.apple.mpegurl",
        "content-length": "4",
        "content-range": "bytes 0-3/4",
        "accept-ranges": "bytes",
        "server": "should-not-leak",
    }

    def __init__(self) -> None:
        self.closed = False

    async def aiter_raw(self):
        yield b"data"

    async def aclose(self) -> None:
        self.closed = True


class FakeAsyncClient:
    instances: list["FakeAsyncClient"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.request: dict[str, object] | None = None
        self.closed = False
        self.upstream = FakeUpstream()
        self.instances.append(self)

    def build_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
    ) -> dict[str, object]:
        return {
            "method": method,
            "url": url,
            "headers": headers,
        }

    async def send(
        self,
        request: dict[str, object],
        *,
        stream: bool,
    ) -> FakeUpstream:
        assert stream is True
        self.request = request
        return self.upstream

    async def aclose(self) -> None:
        self.closed = True


def make_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        secret_key="x" * 40,
        zlm_base_url="http://zlmediakit",
    )
    app.include_router(router)
    return app


def test_media_proxy_streams_allowed_media_and_forwards_range(
    monkeypatch,
) -> None:
    FakeAsyncClient.instances.clear()
    monkeypatch.setattr(
        "app.media_proxy.httpx.AsyncClient",
        FakeAsyncClient,
    )

    with TestClient(make_app()) as client:
        response = client.get(
            (
                "/zlm/zero-nvr/profile-1/hls.m3u8"
                "?zn_exp=123&zn_sig=abc"
            ),
            headers={"range": "bytes=0-3"},
        )

    assert response.status_code == 206
    assert response.content == b"data"
    assert response.headers["content-range"] == "bytes 0-3/4"
    assert response.headers["accept-ranges"] == "bytes"
    assert "server" not in response.headers

    instance = FakeAsyncClient.instances[0]
    assert instance.request is not None
    assert instance.request["url"] == (
        "http://zlmediakit/zero-nvr/profile-1/hls.m3u8"
        "?zn_exp=123&zn_sig=abc"
    )
    assert instance.request["headers"]["range"] == "bytes=0-3"
    assert instance.upstream.closed is True
    assert instance.closed is True


def test_media_proxy_rejects_non_product_zlm_paths(
    monkeypatch,
) -> None:
    FakeAsyncClient.instances.clear()
    monkeypatch.setattr(
        "app.media_proxy.httpx.AsyncClient",
        FakeAsyncClient,
    )

    with TestClient(make_app()) as client:
        response = client.get("/zlm/index/api/version")

    assert response.status_code == 404
    assert FakeAsyncClient.instances == []


def test_media_proxy_head_closes_upstream(
    monkeypatch,
) -> None:
    FakeAsyncClient.instances.clear()
    monkeypatch.setattr(
        "app.media_proxy.httpx.AsyncClient",
        FakeAsyncClient,
    )

    with TestClient(make_app()) as client:
        response = client.head(
            "/zlm/zero-nvr-vod/segment.live.mp4"
        )

    assert response.status_code == 206
    instance = FakeAsyncClient.instances[0]
    assert instance.request["method"] == "HEAD"
    assert instance.upstream.closed is True
    assert instance.closed is True
