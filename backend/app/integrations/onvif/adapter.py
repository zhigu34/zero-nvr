from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

from onvif import ONVIFCamera
from wsdiscovery import QName
from wsdiscovery.discovery import ThreadedWSDiscovery

from app.core.config import Settings


class OnvifIntegrationError(RuntimeError):
    """Sanitized ONVIF integration failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class OnvifDeviceInfo:
    manufacturer: str | None
    model: str | None
    firmware_version: str | None
    serial_number: str | None
    hardware_id: str | None


@dataclass(frozen=True, slots=True)
class OnvifProfileProbe:
    token: str
    name: str
    video_source_token: str | None
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    bitrate_kbps: int | None
    gop_seconds: float | None
    audio_codec: str | None
    has_audio: bool
    stream_uri_available: bool
    stream_uri: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class OnvifInspection:
    device: OnvifDeviceInfo
    capabilities: tuple[str, ...]
    profiles: tuple[OnvifProfileProbe, ...]


@dataclass(frozen=True, slots=True)
class OnvifDiscoveryCandidate:
    candidate_key: str
    epr: str | None
    xaddrs: tuple[str, ...]
    scopes: tuple[str, ...]
    host: str | None
    port: int | None
    device_service_url: str | None


def _read(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _path(value: Any, *names: str) -> Any:
    current = value
    for name in names:
        current = _read(current, name)
        if current is None:
            return None
    return current


def _text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _number(value: Any, cast: Callable[[Any], Any]) -> Any:
    if value is None:
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


class OnvifAdapter:
    """Thin boundary around mature ONVIF and WS-Discovery libraries."""

    def __init__(
        self,
        settings: Settings,
        *,
        camera_factory: Callable[..., Any] = ONVIFCamera,
        discovery_factory: Callable[[], Any] = ThreadedWSDiscovery,
    ) -> None:
        self.settings = settings
        self._camera_factory = camera_factory
        self._discovery_factory = discovery_factory

    async def inspect_device(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> OnvifInspection:
        camera: Any | None = None
        try:
            camera = self._camera_factory(
                host,
                port,
                username,
                password,
                nat_override=True,
                no_cache=True,
            )

            async with asyncio.timeout(self.settings.onvif_timeout_seconds):
                await camera.update_xaddrs()
                raw_device = await camera.devicemgmt.GetDeviceInformation()
                capabilities = await camera.get_capabilities()
                media = camera.create_media_service()
                raw_profiles = await media.GetProfiles()

                device = OnvifDeviceInfo(
                    manufacturer=_text(_read(raw_device, "Manufacturer")),
                    model=_text(_read(raw_device, "Model")),
                    firmware_version=_text(
                        _read(raw_device, "FirmwareVersion")
                    ),
                    serial_number=_text(_read(raw_device, "SerialNumber")),
                    hardware_id=_text(_read(raw_device, "HardwareId")),
                )

                capability_names: tuple[str, ...] = ()
                if isinstance(capabilities, dict):
                    capability_names = tuple(
                        sorted(
                            str(name)
                            for name, value in capabilities.items()
                            if value is not None
                        )
                    )

                profiles: list[OnvifProfileProbe] = []
                for raw_profile in raw_profiles or []:
                    parsed = await self._inspect_profile(media, raw_profile)
                    if parsed is not None:
                        profiles.append(parsed)

                return OnvifInspection(
                    device=device,
                    capabilities=capability_names,
                    profiles=tuple(profiles),
                )
        except TimeoutError as exc:
            raise OnvifIntegrationError(
                "onvif_timeout",
                "The ONVIF device did not respond in time.",
                status_code=504,
            ) from exc
        except OnvifIntegrationError:
            raise
        except Exception as exc:
            # Do not expose raw SOAP/HTTP exception text: some vendors include
            # request URLs or authentication material in their errors.
            raise OnvifIntegrationError(
                "onvif_connection_failed",
                "Unable to inspect the ONVIF device.",
                status_code=422,
            ) from exc
        finally:
            if camera is not None:
                try:
                    await camera.close()
                except Exception:
                    pass

    async def _inspect_profile(
        self,
        media: Any,
        raw_profile: Any,
    ) -> OnvifProfileProbe | None:
        token = _text(
            _read(raw_profile, "token")
            or _read(raw_profile, "Token")
        )
        if token is None:
            return None

        name = _text(_read(raw_profile, "Name")) or token
        video_source_token = _text(
            _path(raw_profile, "VideoSourceConfiguration", "SourceToken")
        )

        video_encoder = _read(raw_profile, "VideoEncoderConfiguration")
        codec = _text(_read(video_encoder, "Encoding"))
        width = _number(_path(video_encoder, "Resolution", "Width"), int)
        height = _number(_path(video_encoder, "Resolution", "Height"), int)
        fps = _number(
            _path(video_encoder, "RateControl", "FrameRateLimit"),
            float,
        )
        bitrate = _number(
            _path(video_encoder, "RateControl", "BitrateLimit"),
            int,
        )

        gov_length = (
            _path(video_encoder, "H264", "GovLength")
            or _path(video_encoder, "H265", "GovLength")
        )
        gov_frames = _number(gov_length, float)
        gop_seconds: float | None = None
        if gov_frames is not None and fps is not None and fps > 0:
            gop_seconds = gov_frames / fps

        audio_encoder = _read(raw_profile, "AudioEncoderConfiguration")
        audio_codec = _text(_read(audio_encoder, "Encoding"))
        has_audio = audio_encoder is not None

        stream_uri: str | None = None
        try:
            request = media.create_type("GetStreamUri")
            request.StreamSetup = {
                "Stream": "RTP-Unicast",
                "Transport": {"Protocol": "RTSP"},
            }
            request.ProfileToken = token
            response = await media.GetStreamUri(request)
            raw_uri = _text(_read(response, "Uri"))
            if raw_uri is not None:
                stream_uri = raw_uri
        except Exception:
            # One broken profile should not make every valid profile disappear.
            stream_uri = None

        return OnvifProfileProbe(
            token=token,
            name=name,
            video_source_token=video_source_token,
            codec=codec.lower() if codec else None,
            width=width,
            height=height,
            fps=fps,
            bitrate_kbps=bitrate,
            gop_seconds=gop_seconds,
            audio_codec=audio_codec.lower() if audio_codec else None,
            has_audio=has_audio,
            stream_uri_available=stream_uri is not None,
            stream_uri=stream_uri,
        )

    async def discover(self) -> list[OnvifDiscoveryCandidate]:
        try:
            return await asyncio.to_thread(self._discover_blocking)
        except OnvifIntegrationError:
            raise
        except Exception as exc:
            raise OnvifIntegrationError(
                "onvif_discovery_failed",
                "ONVIF device discovery failed.",
                status_code=503,
            ) from exc

    def _discover_blocking(self) -> list[OnvifDiscoveryCandidate]:
        discovery = self._discovery_factory()
        try:
            discovery.start()
            services = discovery.searchServices(
                types=[
                    QName(
                        "http://www.onvif.org/ver10/device/wsdl",
                        "Device",
                    )
                ],
                timeout=self.settings.onvif_discovery_timeout_seconds,
            )
        except Exception as exc:
            raise OnvifIntegrationError(
                "onvif_discovery_failed",
                "ONVIF device discovery failed.",
                status_code=503,
            ) from exc
        finally:
            try:
                discovery.stop()
            except Exception:
                pass

        candidates: dict[str, OnvifDiscoveryCandidate] = {}
        for service in services or []:
            epr = _text(service.getEPR())
            xaddrs = tuple(
                sorted(
                    {
                        str(value)
                        for value in (service.getXAddrs() or [])
                        if value
                    }
                )
            )
            scopes = tuple(
                sorted(
                    {
                        str(value)
                        for value in (service.getScopes() or [])
                        if value
                    }
                )
            )

            selected_url: str | None = None
            selected_host: str | None = None
            selected_port: int | None = None
            for xaddr in xaddrs:
                try:
                    parsed = urlsplit(xaddr)
                    if (
                        parsed.scheme.lower() not in {"http", "https"}
                        or not parsed.hostname
                    ):
                        continue
                    selected_url = xaddr
                    selected_host = parsed.hostname
                    selected_port = parsed.port or (
                        443 if parsed.scheme.lower() == "https" else 80
                    )
                    break
                except ValueError:
                    continue

            candidate_key = epr or selected_url
            if candidate_key is None:
                continue

            candidates[candidate_key] = OnvifDiscoveryCandidate(
                candidate_key=candidate_key,
                epr=epr,
                xaddrs=xaddrs,
                scopes=scopes,
                host=selected_host,
                port=selected_port,
                device_service_url=selected_url,
            )

        return sorted(
            candidates.values(),
            key=lambda item: item.candidate_key,
        )
