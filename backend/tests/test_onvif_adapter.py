from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.integrations.onvif import OnvifAdapter, OnvifIntegrationError


USERNAME = "admin"
PASSWORD = "camera-super-secret"


def settings(**overrides) -> Settings:
    values = {
        "secret_key": "o" * 32,
        "onvif_timeout_seconds": 1.0,
        "onvif_discovery_timeout_seconds": 0.1,
    }
    values.update(overrides)
    return Settings(**values)


class FakeDeviceManagement:
    async def GetDeviceInformation(self):
        return SimpleNamespace(
            Manufacturer="Acme",
            Model="Cam X",
            FirmwareVersion="1.2.3",
            SerialNumber="SN-001",
            HardwareId="HW-ABC",
        )


class FakeMedia:
    def __init__(self) -> None:
        self.requests = []

    async def GetProfiles(self):
        main = SimpleNamespace(
            token="main-token",
            Name="Main",
            VideoSourceConfiguration=SimpleNamespace(
                SourceToken="video-source-1"
            ),
            VideoEncoderConfiguration=SimpleNamespace(
                Encoding="H265",
                Resolution=SimpleNamespace(Width=3840, Height=2160),
                RateControl=SimpleNamespace(
                    FrameRateLimit=25,
                    BitrateLimit=8192,
                ),
                H264=None,
                H265=SimpleNamespace(GovLength=50),
            ),
            AudioEncoderConfiguration=SimpleNamespace(Encoding="AAC"),
        )
        sub = SimpleNamespace(
            token="sub-token",
            Name="Sub",
            VideoSourceConfiguration=SimpleNamespace(
                SourceToken="video-source-1"
            ),
            VideoEncoderConfiguration=SimpleNamespace(
                Encoding="H264",
                Resolution=SimpleNamespace(Width=640, Height=360),
                RateControl=SimpleNamespace(
                    FrameRateLimit=10,
                    BitrateLimit=512,
                ),
                H264=SimpleNamespace(GovLength=10),
                H265=None,
            ),
            AudioEncoderConfiguration=None,
        )
        return [main, sub]

    def create_type(self, name: str):
        assert name == "GetStreamUri"
        return SimpleNamespace(StreamSetup=None, ProfileToken=None)

    async def GetStreamUri(self, request):
        self.requests.append(request)
        if request.ProfileToken == "sub-token":
            raise RuntimeError(
                f"vendor error accidentally mentions {PASSWORD}"
            )
        return SimpleNamespace(
            Uri=(
                "rtsp://admin:stream-password@192.168.10.20/live/main"
                "?token=stream-secret"
            )
        )


class FakeCamera:
    instances = []

    def __init__(
        self,
        host,
        port,
        username,
        password,
        **kwargs,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.kwargs = kwargs
        self.devicemgmt = FakeDeviceManagement()
        self.media = FakeMedia()
        self.closed = False
        self.instances.append(self)

    async def update_xaddrs(self) -> None:
        return None

    async def get_capabilities(self):
        return {
            "Media": {"XAddr": "http://camera/onvif/media"},
            "PTZ": {"XAddr": "http://camera/onvif/ptz"},
            "Events": None,
        }

    def create_media_service(self):
        return self.media

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_inspect_device_parses_profiles_closes_and_hides_stream_uri() -> None:
    FakeCamera.instances = []
    adapter = OnvifAdapter(
        settings(),
        camera_factory=FakeCamera,
    )

    result = await adapter.inspect_device(
        host="192.168.10.20",
        port=80,
        username=USERNAME,
        password=PASSWORD,
    )

    assert result.device.manufacturer == "Acme"
    assert result.device.model == "Cam X"
    assert result.device.serial_number == "SN-001"
    assert result.device.hardware_id == "HW-ABC"
    assert result.capabilities == ("Media", "PTZ")
    assert len(result.profiles) == 2

    main, sub = result.profiles

    assert main.token == "main-token"
    assert main.name == "Main"
    assert main.video_source_token == "video-source-1"
    assert main.codec == "h265"
    assert main.width == 3840
    assert main.height == 2160
    assert main.fps == 25.0
    assert main.bitrate_kbps == 8192
    assert main.gop_seconds == 2.0
    assert main.audio_codec == "aac"
    assert main.has_audio is True
    assert main.stream_uri_available is True
    assert main.stream_uri is not None

    # Raw stream URI can contain credentials/tokens and is intentionally
    # excluded from dataclass repr/log-friendly output.
    rendered = repr(result)
    assert "stream-password" not in rendered
    assert "stream-secret" not in rendered
    assert "rtsp://" not in rendered

    # One profile failing GetStreamUri must not discard the valid profile.
    assert sub.codec == "h264"
    assert sub.gop_seconds == 1.0
    assert sub.has_audio is False
    assert sub.stream_uri_available is False
    assert sub.stream_uri is None

    camera = FakeCamera.instances[-1]
    assert camera.kwargs["nat_override"] is True
    assert camera.kwargs["no_cache"] is True
    assert camera.closed is True


class FailingCamera(FakeCamera):
    async def update_xaddrs(self) -> None:
        raise RuntimeError(
            f"authentication failed username={USERNAME} password={PASSWORD}"
        )


@pytest.mark.asyncio
async def test_inspect_device_sanitizes_vendor_errors_and_still_closes() -> None:
    FailingCamera.instances = []
    adapter = OnvifAdapter(
        settings(),
        camera_factory=FailingCamera,
    )

    with pytest.raises(OnvifIntegrationError) as captured:
        await adapter.inspect_device(
            host="192.168.10.20",
            port=80,
            username=USERNAME,
            password=PASSWORD,
        )

    assert captured.value.code == "onvif_connection_failed"
    assert captured.value.status_code == 422
    rendered = str(captured.value)
    assert USERNAME not in rendered
    assert PASSWORD not in rendered
    assert FailingCamera.instances[-1].closed is True


class SlowCamera(FakeCamera):
    async def update_xaddrs(self) -> None:
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_inspect_device_timeout_is_sanitized_and_closes() -> None:
    SlowCamera.instances = []
    adapter = OnvifAdapter(
        settings(onvif_timeout_seconds=0.01),
        camera_factory=SlowCamera,
    )

    with pytest.raises(OnvifIntegrationError) as captured:
        await adapter.inspect_device(
            host="192.168.10.20",
            port=80,
            username=USERNAME,
            password=PASSWORD,
        )

    assert captured.value.code == "onvif_timeout"
    assert captured.value.status_code == 504
    assert SlowCamera.instances[-1].closed is True


class FakeScope:
    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value


class FakeService:
    def __init__(
        self,
        *,
        epr: str,
        xaddrs: list[str],
        scopes: list[str],
    ) -> None:
        self._epr = epr
        self._xaddrs = xaddrs
        self._scopes = scopes

    def getEPR(self):
        return self._epr

    def getXAddrs(self):
        return self._xaddrs

    def getScopes(self):
        return [FakeScope(value) for value in self._scopes]


class FakeDiscovery:
    instances = []

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.timeout = None
        self.types = None
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def searchServices(self, *, types, timeout):
        self.types = types
        self.timeout = timeout
        return [
            FakeService(
                epr="urn:uuid:camera-a",
                xaddrs=[
                    "http://192.168.10.21:8080/onvif/device_service",
                ],
                scopes=[
                    "onvif://www.onvif.org/name/FrontDoor",
                    "onvif://www.onvif.org/Profile/Streaming",
                ],
            ),
            # Same EPR should deterministically replace/dedupe the first row.
            FakeService(
                epr="urn:uuid:camera-a",
                xaddrs=[
                    "http://192.168.10.21:8080/onvif/device_service",
                ],
                scopes=[
                    "onvif://www.onvif.org/name/FrontDoor",
                ],
            ),
            FakeService(
                epr="urn:uuid:camera-b",
                xaddrs=[
                    "not-a-url",
                    "https://camera-b.local/onvif/device_service",
                ],
                scopes=[],
            ),
        ]

    def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_discovery_runs_mature_wsdiscovery_in_thread_and_normalizes() -> None:
    FakeDiscovery.instances = []
    adapter = OnvifAdapter(
        settings(onvif_discovery_timeout_seconds=0.25),
        discovery_factory=FakeDiscovery,
    )

    candidates = await adapter.discover()

    assert len(candidates) == 2
    first, second = candidates

    assert first.candidate_key == "urn:uuid:camera-a"
    assert first.host == "192.168.10.21"
    assert first.port == 8080
    assert first.device_service_url == (
        "http://192.168.10.21:8080/onvif/device_service"
    )

    assert second.candidate_key == "urn:uuid:camera-b"
    assert second.host == "camera-b.local"
    assert second.port == 443
    assert second.device_service_url == (
        "https://camera-b.local/onvif/device_service"
    )

    discovery = FakeDiscovery.instances[-1]
    assert discovery.started is True
    assert discovery.stopped is True
    assert discovery.timeout == 0.25
    assert len(discovery.types) == 1


class FailingDiscovery(FakeDiscovery):
    def searchServices(self, *, types, timeout):
        raise RuntimeError(
            f"raw discovery failure should not leak password={PASSWORD}"
        )


@pytest.mark.asyncio
async def test_discovery_error_is_sanitized_and_stop_is_called() -> None:
    FailingDiscovery.instances = []
    adapter = OnvifAdapter(
        settings(),
        discovery_factory=FailingDiscovery,
    )

    with pytest.raises(OnvifIntegrationError) as captured:
        await adapter.discover()

    assert captured.value.code == "onvif_discovery_failed"
    assert captured.value.status_code == 503
    assert PASSWORD not in str(captured.value)
    assert FailingDiscovery.instances[-1].stopped is True
