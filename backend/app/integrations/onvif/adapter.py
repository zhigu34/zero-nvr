from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import ipaddress
import time
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

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
class OnvifCapabilityProbe:
    supports_snapshot: bool | None = None
    supports_audio: bool | None = None
    supports_time_read: bool | None = None
    supports_time_write: bool | None = None
    supports_ntp_config: bool | None = None


@dataclass(frozen=True, slots=True)
class OnvifInspection:
    device: OnvifDeviceInfo
    capabilities: tuple[str, ...]
    profiles: tuple[OnvifProfileProbe, ...]
    capability_probe: OnvifCapabilityProbe = field(
        default_factory=OnvifCapabilityProbe
    )


@dataclass(frozen=True, slots=True)
class OnvifClockReading:
    utc_datetime: datetime
    date_time_type: str | None
    timezone: str | None
    rtt_ms: float
    offset_ms: float


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


def _safe_http_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    host = parsed.hostname
    if scheme not in {"http", "https"} or not host:
        return None

    display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    try:
        port = parsed.port
    except ValueError:
        return None

    netloc = display_host
    if port is not None:
        netloc = f"{display_host}:{port}"

    # Device-service discovery does not require query or fragment components.
    # Dropping them also prevents accidental persistence of vendor tokens.
    return urlunsplit((scheme, netloc, parsed.path or "", "", ""))


def _number(value: Any, cast: Callable[[Any], Any]) -> Any:
    if value is None:
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _service_operation(
    service: Any,
    name: str,
) -> Callable[..., Any] | None:
    try:
        operation = getattr(service, name)
    except Exception:
        return None
    return operation if callable(operation) else None


def _source_address_key(
    value: Any,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    # WSDiscovery represents IPv6 adapter addresses with a scope suffix.
    # Selection is by the IP itself; the scoped object is retained only
    # when the library opens the actual multicast socket.
    return ipaddress.ip_address(str(value).split("%", 1)[0])


class _SelectedSourceWSDiscovery(ThreadedWSDiscovery):
    """WS-Discovery limited to explicitly selected local source addresses."""

    def __init__(self, source_addresses: tuple[str, ...]) -> None:
        self._selected_source_addresses = frozenset(
            _source_address_key(value)
            for value in source_addresses
        )
        self._active_source_addresses: set[
            ipaddress.IPv4Address | ipaddress.IPv6Address
        ] = set()
        super().__init__()

    @property
    def missing_source_addresses(
        self,
    ) -> frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        return self._selected_source_addresses.difference(
            self._active_source_addresses
        )

    def _networkAddressAdded(self, addr: Any) -> None:
        key = _source_address_key(addr)
        if key in self._selected_source_addresses:
            super()._networkAddressAdded(addr)
            self._active_source_addresses.add(key)

    def _networkAddressRemoved(self, addr: Any) -> None:
        key = _source_address_key(addr)
        if key in self._selected_source_addresses:
            super()._networkAddressRemoved(addr)
            self._active_source_addresses.discard(key)


class OnvifAdapter:
    """Thin boundary around mature ONVIF and WS-Discovery libraries."""

    def __init__(
        self,
        settings: Settings,
        *,
        camera_factory: Callable[..., Any] = ONVIFCamera,
        discovery_factory: Callable[[], Any] = ThreadedWSDiscovery,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._camera_factory = camera_factory
        self._discovery_factory = discovery_factory
        self._wall_clock = (
            wall_clock
            if wall_clock is not None
            else lambda: datetime.now(UTC)
        )
        self._monotonic = monotonic

    async def _probe_snapshot_capability(
        self,
        media: Any,
        raw_profiles: list[Any],
    ) -> bool | None:
        operation = _service_operation(
            media,
            "GetSnapshotUri",
        )
        if operation is None:
            return False

        tokens = [
            token
            for raw_profile in raw_profiles
            if (
                token := _text(
                    _read(raw_profile, "token")
                    or _read(raw_profile, "Token")
                )
            )
            is not None
        ]
        if not tokens:
            return False

        try:
            async with asyncio.timeout(
                min(
                    3.0,
                    self.settings.onvif_timeout_seconds,
                )
            ):
                for token in tokens:
                    try:
                        request = media.create_type(
                            "GetSnapshotUri"
                        )
                        request.ProfileToken = token
                        response = await operation(
                            request
                        )
                    except Exception:
                        continue
                    if _text(
                        _read(response, "Uri")
                    ) is not None:
                        return True
        except TimeoutError:
            return None
        return None

    async def _probe_management_capabilities(
        self,
        devicemgmt: Any,
    ) -> tuple[
        bool | None,
        bool | None,
        bool | None,
    ]:
        get_time = _service_operation(
            devicemgmt,
            "GetSystemDateAndTime",
        )
        set_time = _service_operation(
            devicemgmt,
            "SetSystemDateAndTime",
        )
        get_ntp = _service_operation(
            devicemgmt,
            "GetNTP",
        )
        set_ntp = _service_operation(
            devicemgmt,
            "SetNTP",
        )

        supports_time_read: bool | None = (
            False
            if get_time is None
            else None
        )
        supports_time_write: bool | None = (
            False
            if set_time is None
            else None
        )
        supports_ntp_config: bool | None = (
            False
            if get_ntp is None
            or set_ntp is None
            else None
        )

        try:
            async with asyncio.timeout(
                min(
                    3.0,
                    self.settings.onvif_timeout_seconds,
                )
            ):
                if get_time is not None:
                    try:
                        raw_clock = await get_time()
                        self._parse_utc_datetime(
                            raw_clock
                        )
                        supports_time_read = True
                    except Exception:
                        pass

                if (
                    set_time is not None
                    and supports_time_read is True
                ):
                    # Do not mutate a device clock merely to probe a
                    # capability. A reachable clock API plus an exposed
                    # SetSystemDateAndTime operation is sufficient evidence;
                    # the real write path still verifies the device response.
                    supports_time_write = True

                if (
                    get_ntp is not None
                    and set_ntp is not None
                ):
                    try:
                        await get_ntp()
                        supports_ntp_config = (
                            True
                        )
                    except Exception:
                        pass
        except TimeoutError:
            pass

        return (
            supports_time_read,
            supports_time_write,
            supports_ntp_config,
        )

    async def _probe_optional_capabilities(
        self,
        *,
        devicemgmt: Any,
        media: Any,
        raw_profiles: list[Any],
        profiles: list[OnvifProfileProbe],
    ) -> OnvifCapabilityProbe:
        supports_snapshot = (
            await self._probe_snapshot_capability(
                media,
                raw_profiles,
            )
        )
        (
            supports_time_read,
            supports_time_write,
            supports_ntp_config,
        ) = (
            await self._probe_management_capabilities(
                devicemgmt
            )
        )
        return OnvifCapabilityProbe(
            supports_snapshot=supports_snapshot,
            supports_audio=any(
                profile.has_audio
                for profile in profiles
            ),
            supports_time_read=supports_time_read,
            supports_time_write=supports_time_write,
            supports_ntp_config=supports_ntp_config,
        )

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
                raw_profiles = list(
                    await media.GetProfiles() or []
                )

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
                for raw_profile in raw_profiles:
                    parsed = await self._inspect_profile(
                        media,
                        raw_profile,
                    )
                    if parsed is not None:
                        profiles.append(parsed)

            capability_probe = (
                await self._probe_optional_capabilities(
                    devicemgmt=camera.devicemgmt,
                    media=media,
                    raw_profiles=raw_profiles,
                    profiles=profiles,
                )
            )
            return OnvifInspection(
                device=device,
                capabilities=capability_names,
                profiles=tuple(profiles),
                capability_probe=capability_probe,
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

    @staticmethod
    def _select_ptz_profile(
        raw_profiles: list[Any],
        preferred_tokens: tuple[str, ...],
    ) -> str:
        candidates: list[str] = []
        for raw_profile in raw_profiles:
            token = _text(
                _read(raw_profile, "token")
                or _read(raw_profile, "Token")
            )
            configuration = _read(
                raw_profile,
                "PTZConfiguration",
            )
            if token is not None and configuration is not None:
                candidates.append(token)

        for token in preferred_tokens:
            if token in candidates:
                return token
        if candidates:
            return candidates[0]

        raise OnvifIntegrationError(
            "onvif_ptz_profile_unavailable",
            "The ONVIF device has no media profile with PTZ configuration.",
            status_code=409,
        )

    @staticmethod
    def _ntp_host(value: str) -> dict[str, str]:
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError:
            return {
                "Type": "DNS",
                "DNSname": value,
            }
        if parsed.version == 4:
            return {
                "Type": "IPv4",
                "IPv4Address": str(parsed),
            }
        return {
            "Type": "IPv6",
            "IPv6Address": str(parsed),
        }

    @staticmethod
    def _parse_utc_datetime(value: Any) -> datetime:
        year = _number(
            _path(value, "UTCDateTime", "Date", "Year"),
            int,
        )
        month = _number(
            _path(value, "UTCDateTime", "Date", "Month"),
            int,
        )
        day = _number(
            _path(value, "UTCDateTime", "Date", "Day"),
            int,
        )
        hour = _number(
            _path(value, "UTCDateTime", "Time", "Hour"),
            int,
        )
        minute = _number(
            _path(value, "UTCDateTime", "Time", "Minute"),
            int,
        )
        second = _number(
            _path(value, "UTCDateTime", "Time", "Second"),
            int,
        )
        parts = (year, month, day, hour, minute, second)
        if any(item is None for item in parts):
            raise OnvifIntegrationError(
                "onvif_clock_invalid",
                "The ONVIF device did not return a valid UTC clock.",
                status_code=422,
            )
        try:
            return datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                min(59, max(0, int(second))),
                tzinfo=UTC,
            )
        except ValueError as exc:
            raise OnvifIntegrationError(
                "onvif_clock_invalid",
                "The ONVIF device returned an invalid UTC clock.",
                status_code=422,
            ) from exc

    async def read_system_clock(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> OnvifClockReading:
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
            async with asyncio.timeout(
                self.settings.onvif_timeout_seconds
            ):
                await camera.update_xaddrs()
                wall_started = self._wall_clock()
                mono_started = self._monotonic()
                raw = await camera.devicemgmt.GetSystemDateAndTime()
                mono_ended = self._monotonic()
                wall_ended = self._wall_clock()

            camera_utc = self._parse_utc_datetime(raw)
            midpoint = wall_started + (
                (wall_ended - wall_started) / 2
            )
            return OnvifClockReading(
                utc_datetime=camera_utc,
                date_time_type=_text(
                    _read(raw, "DateTimeType")
                ),
                timezone=_text(
                    _path(raw, "TimeZone", "TZ")
                ),
                rtt_ms=max(
                    0.0,
                    (mono_ended - mono_started) * 1000.0,
                ),
                offset_ms=(
                    camera_utc - midpoint
                ).total_seconds() * 1000.0,
            )
        except TimeoutError as exc:
            raise OnvifIntegrationError(
                "onvif_clock_timeout",
                "The ONVIF clock check timed out.",
                status_code=504,
            ) from exc
        except OnvifIntegrationError:
            raise
        except Exception as exc:
            raise OnvifIntegrationError(
                "onvif_clock_failed",
                "Unable to read the ONVIF device clock.",
                status_code=422,
            ) from exc
        finally:
            if camera is not None:
                try:
                    await camera.close()
                except Exception:
                    pass

    async def configure_ntp(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        servers: tuple[str, ...],
    ) -> None:
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
            async with asyncio.timeout(
                self.settings.onvif_timeout_seconds
            ):
                await camera.update_xaddrs()
                if servers:
                    await camera.devicemgmt.SetNTP(
                        {
                            "FromDHCP": False,
                            "NTPManual": [
                                self._ntp_host(item)
                                for item in servers
                            ],
                        }
                    )
                else:
                    await camera.devicemgmt.SetNTP(
                        {
                            "FromDHCP": True,
                        }
                    )
                await camera.devicemgmt.SetSystemDateAndTime(
                    {
                        "DateTimeType": "NTP",
                        "DaylightSavings": False,
                    }
                )
        except TimeoutError as exc:
            raise OnvifIntegrationError(
                "onvif_ntp_timeout",
                "The ONVIF NTP update timed out.",
                status_code=504,
            ) from exc
        except OnvifIntegrationError:
            raise
        except Exception as exc:
            raise OnvifIntegrationError(
                "onvif_ntp_failed",
                "The ONVIF device rejected the NTP configuration.",
                status_code=422,
            ) from exc
        finally:
            if camera is not None:
                try:
                    await camera.close()
                except Exception:
                    pass

    async def ptz_move(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        preferred_profile_tokens: tuple[str, ...] = (),
        pan: float = 0.0,
        tilt: float = 0.0,
        zoom: float = 0.0,
    ) -> None:
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
            async with asyncio.timeout(
                self.settings.onvif_timeout_seconds
            ):
                await camera.update_xaddrs()
                media = camera.create_media_service()
                ptz = camera.create_ptz_service()
                raw_profiles = list(
                    await media.GetProfiles() or []
                )
                profile_token = self._select_ptz_profile(
                    raw_profiles,
                    preferred_profile_tokens,
                )
                velocity: dict[str, object] = {}
                if pan != 0.0 or tilt != 0.0:
                    velocity["PanTilt"] = {
                        "x": float(pan),
                        "y": float(tilt),
                    }
                if zoom != 0.0:
                    velocity["Zoom"] = {
                        "x": float(zoom),
                    }
                if not velocity:
                    raise OnvifIntegrationError(
                        "onvif_ptz_move_invalid",
                        "PTZ move requires non-zero velocity.",
                        status_code=400,
                    )
                await ptz.ContinuousMove(
                    {
                        "ProfileToken": profile_token,
                        "Velocity": velocity,
                    }
                )
        except TimeoutError as exc:
            raise OnvifIntegrationError(
                "onvif_ptz_timeout",
                "The ONVIF PTZ command timed out.",
                status_code=504,
            ) from exc
        except OnvifIntegrationError:
            raise
        except Exception as exc:
            raise OnvifIntegrationError(
                "onvif_ptz_failed",
                "The ONVIF PTZ command failed.",
                status_code=422,
            ) from exc
        finally:
            if camera is not None:
                try:
                    await camera.close()
                except Exception:
                    pass

    async def ptz_stop(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        preferred_profile_tokens: tuple[str, ...] = (),
    ) -> None:
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
            async with asyncio.timeout(
                self.settings.onvif_timeout_seconds
            ):
                await camera.update_xaddrs()
                media = camera.create_media_service()
                ptz = camera.create_ptz_service()
                raw_profiles = list(
                    await media.GetProfiles() or []
                )
                profile_token = self._select_ptz_profile(
                    raw_profiles,
                    preferred_profile_tokens,
                )
                await ptz.Stop(
                    {
                        "ProfileToken": profile_token,
                        "PanTilt": True,
                        "Zoom": True,
                    }
                )
        except TimeoutError as exc:
            raise OnvifIntegrationError(
                "onvif_ptz_timeout",
                "The ONVIF PTZ stop command timed out.",
                status_code=504,
            ) from exc
        except OnvifIntegrationError:
            raise
        except Exception as exc:
            raise OnvifIntegrationError(
                "onvif_ptz_failed",
                "The ONVIF PTZ stop command failed.",
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

    async def discover(
        self,
        *,
        source_addresses: tuple[str, ...] = (),
    ) -> list[OnvifDiscoveryCandidate]:
        try:
            return await asyncio.to_thread(
                self._discover_blocking,
                source_addresses,
            )
        except OnvifIntegrationError:
            raise
        except Exception as exc:
            raise OnvifIntegrationError(
                "onvif_discovery_failed",
                "ONVIF device discovery failed.",
                status_code=503,
            ) from exc

    def _discover_blocking(
        self,
        source_addresses: tuple[str, ...],
    ) -> list[OnvifDiscoveryCandidate]:
        if (
            source_addresses
            and self._discovery_factory is ThreadedWSDiscovery
        ):
            discovery = _SelectedSourceWSDiscovery(source_addresses)
        else:
            discovery = self._discovery_factory()
        try:
            discovery.start()
            if (
                isinstance(discovery, _SelectedSourceWSDiscovery)
                and discovery.missing_source_addresses
            ):
                raise OnvifIntegrationError(
                    "onvif_discovery_source_address_unavailable",
                    "A selected ONVIF discovery source address is not "
                    "available on this host.",
                    status_code=422,
                )
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
                        safe
                        for value in (service.getXAddrs() or [])
                        if value
                        for safe in [_safe_http_url(str(value))]
                        if safe is not None
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
                    if not parsed.hostname:
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
