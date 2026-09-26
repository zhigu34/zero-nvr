from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit
import uuid

import httpx

from app.core.config import Settings


class ZlmIntegrationError(RuntimeError):
    """Sanitized ZLM integration failure.

    Never include raw request arguments or ZLM response text here because the
    source URL can contain camera credentials/tokens.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ZlmTrackProbe:
    kind: str
    codec: str | None
    ready: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    gop_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None


@dataclass(frozen=True, slots=True)
class ZlmMediaProbe:
    stream: str
    video: ZlmTrackProbe | None
    audio: ZlmTrackProbe | None


@dataclass(frozen=True, slots=True)
class ZlmWhepSession:
    answer_sdp: str
    session_id: str
    session_token: str


MP4_RECORD_TYPE = 1


class ZlmAdapter:
    """Minimal ZLMediaKit control adapter.

    ZLM's API argument parser accepts application/x-www-form-urlencoded body
    fields. Sensitive values therefore stay out of the request URL.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = 0.25,
        timeout_seconds: float | None = None,
    ) -> None:
        self.settings = settings
        self._sleep = sleep
        self._monotonic = monotonic
        self._poll_interval_seconds = poll_interval_seconds
        self._client = httpx.Client(
            base_url=settings.zlm_base_url,
            timeout=(
                timeout_seconds
                if timeout_seconds is not None
                else settings.zlm_timeout_seconds
            ),
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ZlmAdapter":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _api_secret(self) -> str:
        if self.settings.zlm_api_secret is None:
            raise ZlmIntegrationError(
                "zlm_not_configured",
                "ZLMediaKit API secret is not configured.",
                status_code=503,
            )
        return self.settings.zlm_api_secret.get_secret_value()

    @staticmethod
    def _form_value(value: object) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)

    def _call(
        self,
        api: str,
        *,
        params: dict[str, object] | None = None,
        accepted_error: tuple[int, str] | None = None,
    ) -> dict[str, Any]:
        form = {
            "secret": self._api_secret(),
            **{
                key: self._form_value(value)
                for key, value in (params or {}).items()
                if value is not None
            },
        }

        try:
            response = self._client.post(
                f"/index/api/{api}",
                data=form,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ZlmIntegrationError(
                "zlm_timeout",
                "ZLMediaKit did not respond in time.",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ZlmIntegrationError(
                "zlm_unavailable",
                "ZLMediaKit request failed.",
                status_code=503,
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ZlmIntegrationError(
                "zlm_invalid_response",
                "ZLMediaKit returned an invalid response.",
            ) from exc

        if not isinstance(payload, dict):
            raise ZlmIntegrationError(
                "zlm_invalid_response",
                "ZLMediaKit returned an invalid response.",
            )

        code = payload.get("code", 0)
        try:
            numeric_code = int(code)
        except (TypeError, ValueError):
            numeric_code = -1

        if numeric_code != 0:
            raw_message = payload.get("msg")
            if (
                accepted_error is not None
                and numeric_code == accepted_error[0]
                and raw_message == accepted_error[1]
            ):
                return payload
            # Deliberately ignore raw msg/data because they can echo input URLs.
            raise ZlmIntegrationError(
                "zlm_operation_failed",
                f"ZLMediaKit operation {api} failed (code {numeric_code}).",
            )

        return payload

    def whep_play(
        self,
        *,
        app: str,
        stream: str,
        offer_sdp: str,
        playback_params: dict[str, str],
        preferred_tcp: bool = False,
        candidate_udp: str | None = None,
        candidate_tcp: str | None = None,
        max_sdp_bytes: int = 256 * 1024,
    ) -> ZlmWhepSession:
        offer_bytes = offer_sdp.encode("utf-8")
        if (
            not offer_bytes
            or len(offer_bytes) > max_sdp_bytes
        ):
            raise ZlmIntegrationError(
                "zlm_whep_offer_invalid",
                "WebRTC offer SDP is invalid.",
                status_code=422,
            )

        params: dict[str, object] = {
            "app": app,
            "stream": stream,
            **playback_params,
        }
        if preferred_tcp:
            params["preferred_tcp"] = 1
        if candidate_udp:
            params["cand_udp"] = candidate_udp
        if candidate_tcp:
            params["cand_tcp"] = candidate_tcp

        whep_timeout = httpx.Timeout(
            connect=self.settings.zlm_timeout_seconds,
            read=None,
            write=self.settings.zlm_timeout_seconds,
            pool=self.settings.zlm_timeout_seconds,
        )
        try:
            response = self._client.post(
                "/index/api/whep",
                params=params,
                content=offer_bytes,
                headers={
                    "Accept": "application/sdp",
                    "Content-Type": "application/sdp",
                },
                timeout=whep_timeout,
            )
        except httpx.TimeoutException as exc:
            raise ZlmIntegrationError(
                "zlm_whep_timeout",
                "ZLMediaKit WebRTC negotiation timed out.",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ZlmIntegrationError(
                "zlm_whep_unavailable",
                "ZLMediaKit WebRTC negotiation failed.",
                status_code=503,
            ) from exc

        if response.status_code != 201:
            raise ZlmIntegrationError(
                "zlm_whep_negotiation_failed",
                "ZLMediaKit rejected the WebRTC negotiation.",
                status_code=502,
            )

        content_type = response.headers.get(
            "content-type",
            "",
        ).split(";", 1)[0].strip().lower()
        answer_sdp = response.text
        if (
            content_type != "application/sdp"
            or not answer_sdp
            or len(answer_sdp.encode("utf-8"))
            > max_sdp_bytes
        ):
            raise ZlmIntegrationError(
                "zlm_whep_invalid_response",
                "ZLMediaKit returned an invalid WebRTC answer.",
            )

        location = response.headers.get("location", "")
        parsed = urlsplit(location)
        query = parse_qs(
            parsed.query,
            keep_blank_values=True,
        )
        ids = query.get("id", [])
        tokens = query.get("token", [])
        if (
            not parsed.path.endswith(
                "/index/api/delete_webrtc"
            )
            or len(ids) != 1
            or len(tokens) != 1
            or not ids[0]
            or not tokens[0]
            or len(ids[0]) > 512
            or len(tokens[0]) > 2048
        ):
            raise ZlmIntegrationError(
                "zlm_whep_invalid_response",
                "ZLMediaKit returned invalid WebRTC session metadata.",
            )

        return ZlmWhepSession(
            answer_sdp=answer_sdp,
            session_id=ids[0],
            session_token=tokens[0],
        )

    def delete_webrtc(
        self,
        *,
        session_id: str,
        session_token: str,
    ) -> None:
        if (
            not session_id
            or not session_token
            or len(session_id) > 512
            or len(session_token) > 2048
        ):
            raise ZlmIntegrationError(
                "zlm_whep_session_invalid",
                "WebRTC session metadata is invalid.",
                status_code=422,
            )
        try:
            response = self._client.delete(
                "/index/api/delete_webrtc",
                params={
                    "id": session_id,
                    "token": session_token,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ZlmIntegrationError(
                "zlm_whep_cleanup_timeout",
                "ZLMediaKit WebRTC cleanup timed out.",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ZlmIntegrationError(
                "zlm_whep_cleanup_failed",
                "ZLMediaKit WebRTC cleanup failed.",
                status_code=503,
            ) from exc

        content_type = response.headers.get(
            "content-type",
            "",
        ).split(";", 1)[0].strip().lower()
        if content_type == "application/json":
            try:
                payload = response.json()
            except ValueError as exc:
                raise ZlmIntegrationError(
                    "zlm_whep_invalid_response",
                    "ZLMediaKit returned an invalid WebRTC cleanup response.",
                ) from exc
            if isinstance(payload, dict):
                code = payload.get("code", 0)
                try:
                    numeric_code = int(code)
                except (TypeError, ValueError):
                    numeric_code = -1
                if numeric_code != 0:
                    raise ZlmIntegrationError(
                        "zlm_whep_cleanup_failed",
                        "ZLMediaKit rejected WebRTC cleanup.",
                        status_code=502,
                    )

    def snapshot(
        self,
        *,
        source_url: str,
        timeout_seconds: int = 10,
        expire_seconds: int = 3,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> tuple[bytes, str]:
        form = {
            "secret": self._api_secret(),
            "url": source_url,
            "timeout_sec": self._form_value(timeout_seconds),
            "expire_sec": self._form_value(expire_seconds),
        }
        try:
            response = self._client.post(
                "/index/api/getSnap",
                data=form,
                headers={"Accept": "image/jpeg"},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ZlmIntegrationError(
                "zlm_snapshot_timeout",
                "ZLMediaKit snapshot did not complete in time.",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ZlmIntegrationError(
                "zlm_unavailable",
                "ZLMediaKit snapshot request failed.",
                status_code=503,
            ) from exc

        content_type = response.headers.get(
            "content-type",
            "",
        ).split(";", 1)[0].strip().lower()
        content = response.content
        if content_type not in {"image/jpeg", "image/jpg"}:
            raise ZlmIntegrationError(
                "zlm_snapshot_failed",
                "ZLMediaKit could not produce a camera snapshot.",
            )
        if not content or len(content) > max_bytes:
            raise ZlmIntegrationError(
                "zlm_snapshot_invalid",
                "ZLMediaKit returned an invalid camera snapshot.",
            )
        return content, "image/jpeg"

    def version(self) -> dict[str, str | None]:
        payload = self._call("version")
        data = payload.get("data")
        if not isinstance(data, dict):
            data = payload

        def safe_text(key: str) -> str | None:
            value = data.get(key)
            return str(value) if value is not None else None

        return {
            "branch": safe_text("branchName"),
            "commit": safe_text("commitHash"),
            "build_time": safe_text("buildTime"),
            "version": safe_text("version"),
        }

    def add_stream_proxy(
        self,
        *,
        app: str,
        stream: str,
        source_url: str,
        enable_mp4: bool = False,
        enable_hls: bool = False,
        mp4_save_path: str | None = None,
        mp4_max_second: int | None = None,
        retry_count: int = -1,
        auto_close: bool = False,
        mp4_as_player: bool = False,
    ) -> str:
        payload = self._call(
            "addStreamProxy",
            params={
                "vhost": "__defaultVhost__",
                "app": app,
                "stream": stream,
                "url": source_url,
                "rtp_type": 0,
                "retry_count": retry_count,
                "auto_close": auto_close,
                "mp4_as_player": mp4_as_player,
                "enable_hls": enable_hls,
                "enable_mp4": enable_mp4,
                "enable_rtsp": 1,
                "enable_rtmp": 0,
                "enable_ts": 0,
                "enable_fmp4": 0,
                "enable_audio": 1,
                "add_mute_audio": 0,
                "mp4_save_path": mp4_save_path,
                "mp4_max_second": mp4_max_second,
            },
            accepted_error=(-1, "This stream already exists"),
        )
        data = payload.get("data")
        key = data.get("key") if isinstance(data, dict) else None
        if (
            (not isinstance(key, str) or not key)
            and payload.get("code") == -1
            and payload.get("msg") == "This stream already exists"
        ):
            return f"__defaultVhost__/{app}/{stream}"
        if not isinstance(key, str) or not key:
            raise ZlmIntegrationError(
                "zlm_invalid_response",
                "ZLMediaKit did not return a stream proxy key.",
            )
        return key

    def delete_stream_proxy(self, key: str) -> None:
        self._call("delStreamProxy", params={"key": key})

    def is_media_online(
        self,
        *,
        app: str,
        stream: str,
        schema: str = "rtsp",
    ) -> bool:
        payload = self._call(
            "isMediaOnline",
            params={
                "schema": schema,
                "vhost": "__defaultVhost__",
                "app": app,
                "stream": stream,
            },
        )
        return bool(payload.get("online", False))

    def wait_media_online(
        self,
        *,
        app: str,
        stream: str,
        timeout_seconds: float,
        schema: str = "rtsp",
    ) -> bool:
        deadline = self._monotonic() + max(
            0.0,
            timeout_seconds,
        )
        while True:
            if self.is_media_online(
                app=app,
                stream=stream,
                schema=schema,
            ):
                return True

            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return False
            self._sleep(
                min(
                    self._poll_interval_seconds,
                    remaining,
                )
            )

    def wait_video_ready(
        self,
        *,
        app: str,
        stream: str,
        timeout_seconds: float,
        schema: str = "rtsp",
    ) -> bool:
        deadline = self._monotonic() + max(
            0.0,
            timeout_seconds,
        )
        while True:
            probe = self.media_probe(
                app=app,
                stream=stream,
                schema=schema,
            )
            if (
                probe is not None
                and probe.video is not None
                and probe.video.ready
            ):
                return True

            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return False
            self._sleep(
                min(
                    self._poll_interval_seconds,
                    remaining,
                )
            )

    def close_stream(
        self,
        *,
        app: str,
        stream: str,
        schema: str = "rtsp",
        force: bool = True,
    ) -> bool:
        payload = self._call(
            "close_stream",
            params={
                "schema": schema,
                "vhost": "__defaultVhost__",
                "app": app,
                "stream": stream,
                "force": force,
            },
        )
        result = payload.get("result")
        try:
            return int(result) == 0
        except (TypeError, ValueError):
            return False

    def load_mp4_file(
        self,
        *,
        app: str,
        stream: str,
        file_path: str,
        seek_ms: int = 0,
        speed: float = 1.0,
    ) -> bool:
        payload = self._call(
            "loadMP4File",
            params={
                "vhost": "__defaultVhost__",
                "app": app,
                "stream": stream,
                "file_path": file_path,
                "file_repeat": 0,
                "seek_ms": max(0, seek_ms),
                "speed": speed,
                "enable_hls": 0,
                "enable_hls_fmp4": 0,
                "enable_mp4": 0,
                "enable_rtsp": 1,
                "enable_rtmp": 0,
                "enable_ts": 0,
                "enable_fmp4": 1,
                "enable_audio": 1,
                "add_mute_audio": 0,
                "modify_stamp": 2,
                "auto_close": 1,
            },
        )
        return bool(payload.get("result", True))

    def start_mp4_recording(
        self,
        *,
        app: str,
        stream: str,
        customized_path: str,
        max_second: int,
    ) -> bool:
        payload = self._call(
            "startRecord",
            params={
                "type": MP4_RECORD_TYPE,
                "vhost": "__defaultVhost__",
                "app": app,
                "stream": stream,
                "customized_path": customized_path,
                "max_second": max_second,
            },
        )
        return bool(payload.get("result", True))

    def stop_mp4_recording(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool:
        payload = self._call(
            "stopRecord",
            params={
                "type": MP4_RECORD_TYPE,
                "vhost": "__defaultVhost__",
                "app": app,
                "stream": stream,
            },
        )
        return bool(payload.get("result", True))

    def is_mp4_recording(
        self,
        *,
        app: str,
        stream: str,
    ) -> bool:
        payload = self._call(
            "isRecording",
            params={
                "type": MP4_RECORD_TYPE,
                "vhost": "__defaultVhost__",
                "app": app,
                "stream": stream,
            },
        )
        return bool(payload.get("status", False))

    def get_media_list(
        self,
        *,
        app: str,
        stream: str,
        schema: str = "rtsp",
    ) -> list[dict[str, Any]]:
        payload = self._call(
            "getMediaList",
            params={
                "schema": schema,
                "vhost": "__defaultVhost__",
                "app": app,
                "stream": stream,
            },
        )
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def media_probe(
        self,
        *,
        app: str,
        stream: str,
        schema: str = "rtsp",
    ) -> ZlmMediaProbe | None:
        items = self.get_media_list(
            app=app,
            stream=stream,
            schema=schema,
        )
        for item in items:
            probe = self._parse_tracks(item)
            if not probe.stream or probe.stream == stream:
                return probe
        return None

    @staticmethod
    def _parse_tracks(item: dict[str, Any]) -> ZlmMediaProbe:
        video: ZlmTrackProbe | None = None
        audio: ZlmTrackProbe | None = None

        tracks = item.get("tracks")
        if not isinstance(tracks, list):
            tracks = []

        for raw in tracks:
            if not isinstance(raw, dict):
                continue

            codec = raw.get("codec_id_name")
            codec_name = str(codec).lower() if codec is not None else None
            ready = bool(raw.get("ready", False))

            if "width" in raw or "height" in raw or "gop_interval_ms" in raw:
                interval_ms = raw.get("gop_interval_ms")
                gop_seconds: float | None = None
                if isinstance(interval_ms, (int, float)) and interval_ms > 0:
                    gop_seconds = float(interval_ms) / 1000.0

                fps = raw.get("fps")
                video = ZlmTrackProbe(
                    kind="video",
                    codec=codec_name,
                    ready=ready,
                    width=int(raw["width"]) if isinstance(raw.get("width"), (int, float)) else None,
                    height=int(raw["height"]) if isinstance(raw.get("height"), (int, float)) else None,
                    fps=float(fps) if isinstance(fps, (int, float)) else None,
                    gop_seconds=gop_seconds,
                )
                continue

            if "sample_rate" in raw or "channels" in raw:
                audio = ZlmTrackProbe(
                    kind="audio",
                    codec=codec_name,
                    ready=ready,
                    sample_rate=(
                        int(raw["sample_rate"])
                        if isinstance(raw.get("sample_rate"), (int, float))
                        else None
                    ),
                    channels=(
                        int(raw["channels"])
                        if isinstance(raw.get("channels"), (int, float))
                        else None
                    ),
                )

        return ZlmMediaProbe(
            stream=str(item.get("stream") or ""),
            video=video,
            audio=audio,
        )

    def probe_rtsp_source(self, source_url: str) -> ZlmMediaProbe:
        """Temporarily pull one RTSP source through ZLM and inspect tracks."""

        app = "zero-nvr-probe"
        stream = f"probe-{uuid.uuid4().hex}"
        proxy_key: str | None = None
        deadline = self._monotonic() + self.settings.zlm_probe_timeout_seconds

        try:
            proxy_key = self.add_stream_proxy(
                app=app,
                stream=stream,
                source_url=source_url,
                enable_mp4=False,
                retry_count=0,
            )

            while self._monotonic() < deadline:
                items = self.get_media_list(app=app, stream=stream)
                for item in items:
                    probe = self._parse_tracks(item)
                    if probe.video is not None and probe.video.ready:
                        return probe
                self._sleep(self._poll_interval_seconds)

            raise ZlmIntegrationError(
                "camera_stream_probe_timeout",
                "The camera stream did not become ready in time.",
                status_code=422,
            )
        finally:
            if proxy_key is not None:
                try:
                    self.delete_stream_proxy(proxy_key)
                except ZlmIntegrationError:
                    # Probe cleanup failure must never replace the primary result
                    # or leak the sensitive source URL.
                    pass
