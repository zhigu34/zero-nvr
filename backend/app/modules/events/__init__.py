"""Canonical provider-neutral Event ownership."""

from .onvif import (
    OnvifEventIngestResult,
    OnvifEventIngestService,
)

__all__ = [
    "OnvifEventIngestResult",
    "OnvifEventIngestService",
]
