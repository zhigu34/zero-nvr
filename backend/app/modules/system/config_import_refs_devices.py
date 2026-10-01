"""Validate endpoint and credential ownership within devices."""

from __future__ import annotations

from .config_import_document import ParsedSections
from .config_import_reference_ids import ReferenceIds


def validate_devices_references(service: type, parsed: ParsedSections, ids: ReferenceIds) -> None:
    endpoints = parsed.endpoints
    device_credentials = parsed.device_credentials
    device_ids = ids.device_ids
    endpoint_ids = ids.endpoint_ids

    endpoint_devices: dict[str, str] = {}
    for index, item in enumerate(endpoints):
        device_id = service._require_ref(
            item.get("device_id"),
            device_ids,
            path=(
                "$.sections.devices.endpoints"
                f"[{index}].device_id"
            ),
        )
        assert device_id is not None
        endpoint_devices[
            str(item["id"])
        ] = device_id

    for index, item in enumerate(
        device_credentials
    ):
        device_id = service._require_ref(
            item.get("device_id"),
            device_ids,
            path=(
                "$.sections.devices.credentials"
                f"[{index}].device_id"
            ),
        )
        endpoint_id = item.get(
            "endpoint_id"
        )
        if endpoint_id is not None:
            endpoint = service._require_ref(
                endpoint_id,
                endpoint_ids,
                path=(
                    "$.sections.devices.credentials"
                    f"[{index}].endpoint_id"
                ),
            )
            assert endpoint is not None
            if (
                endpoint_devices.get(endpoint)
                != device_id
            ):
                raise service._error(
                    "configuration_import_reference_invalid",
                    "Device credential endpoint belongs to a different device.",
                    details={
                        "path": (
                            "$.sections.devices.credentials"
                            f"[{index}].endpoint_id"
                        )
                    },
                )

