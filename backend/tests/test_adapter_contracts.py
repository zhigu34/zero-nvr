from __future__ import annotations

from pathlib import Path

import app.integrations.contracts as contracts_module
from app.integrations.apprise import AppriseAdapter
from app.integrations.contracts import (
    DetectionProvider,
    DeviceAdapter,
    EmailBackend,
    MediaPlane,
    NotificationBackend,
    RecordingBackend,
    StorageBackend,
)
from app.integrations.frigate import FrigateHttpAdapter
from app.integrations.onvif import OnvifAdapter
from app.integrations.rclone import RcloneAdapter
from app.integrations.smtp import SmtpAdapter
from app.integrations.zlm import (
    ZlmAdapter,
    ZlmRecordingAdapter,
)


def _uninitialized(cls):
    return object.__new__(cls)


def test_current_integrations_satisfy_structural_adapter_contracts() -> None:
    assert isinstance(
        _uninitialized(OnvifAdapter),
        DeviceAdapter,
    )
    assert isinstance(
        _uninitialized(ZlmAdapter),
        MediaPlane,
    )
    assert isinstance(
        _uninitialized(ZlmRecordingAdapter),
        RecordingBackend,
    )
    assert isinstance(
        _uninitialized(RcloneAdapter),
        StorageBackend,
    )
    assert isinstance(
        _uninitialized(AppriseAdapter),
        NotificationBackend,
    )
    assert isinstance(
        _uninitialized(SmtpAdapter),
        EmailBackend,
    )
    assert isinstance(
        _uninitialized(FrigateHttpAdapter),
        DetectionProvider,
    )


def test_adapter_contracts_do_not_depend_on_domain_modules() -> None:
    source = Path(
        contracts_module.__file__
    ).read_text(
        encoding="utf-8"
    )
    assert "app.modules." not in source
