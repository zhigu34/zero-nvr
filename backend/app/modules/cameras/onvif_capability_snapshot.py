from __future__ import annotations

from typing import Any

from app.integrations.onvif import OnvifInspection


CAPABILITY_SNAPSHOT_SCHEMA_VERSION = 1


def build_onvif_capability_snapshot(
    inspection: OnvifInspection,
) -> dict[str, Any]:
    """Normalize facts already learned by the ONVIF inspection.

    Unknown optional capabilities stay None until their dedicated probe runs.
    This keeps the frozen devices.capabilities_json schema honest: absence of
    a probe is distinct from a confirmed unsupported capability.
    """

    services = sorted(set(inspection.capabilities))
    service_set = set(services)
    probe = inspection.capability_probe
    supports_audio = (
        probe.supports_audio
        if probe.supports_audio is not None
        else any(
            profile.has_audio
            for profile in inspection.profiles
        )
    )
    return {
        "schema_version": CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
        "adapter": "onvif",
        "onvif_services": services,
        "supports_events": "Events" in service_set,
        "event_types": None,
        "supports_ptz": "PTZ" in service_set,
        "ptz_features": None,
        "supports_snapshot": probe.supports_snapshot,
        "supports_audio": supports_audio,
        "supports_two_way_audio": None,
        "supports_time_read": probe.supports_time_read,
        "supports_time_write": probe.supports_time_write,
        "supports_ntp_config": probe.supports_ntp_config,
        "supports_profile_management": None,
        "supports_reboot": None,
        "vendor_capabilities": {},
        "adapter_version": None,
    }
