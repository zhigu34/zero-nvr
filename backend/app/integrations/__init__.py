"""Thin adapters around mature external components."""

from .contracts import (
    DetectionProvider,
    DeviceAdapter,
    EmailBackend,
    IntegrationAdapter,
    MediaPlane,
    NotificationBackend,
    RecordingBackend,
    StorageBackend,
)

__all__ = [
    "DetectionProvider",
    "DeviceAdapter",
    "EmailBackend",
    "IntegrationAdapter",
    "MediaPlane",
    "NotificationBackend",
    "RecordingBackend",
    "StorageBackend",
]
