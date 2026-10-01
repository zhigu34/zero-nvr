"""Apply device metadata while preserving local endpoints and credentials."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
import uuid

from sqlalchemy.orm import Session

from .config_import_support import ConfigurationApplyItem
from .config_import_device_matching import match_existing_device


def apply_devices(
    service: type,
    session: Session,
    *,
    sections: dict[str, Any],
    applied: list[ConfigurationApplyItem],
    skipped: list[ConfigurationApplyItem],
    device_map: dict[str, uuid.UUID],
) -> None:
    devices_section = sections.get(
        "devices",
        {},
    )
    assert isinstance(
        devices_section,
        dict,
    )
    devices = devices_section.get(
        "devices",
        [],
    )
    endpoints = devices_section.get(
        "endpoints",
        [],
    )
    credentials = devices_section.get(
        "credentials",
        [],
    )
    assert isinstance(devices, list)
    assert isinstance(endpoints, list)
    assert isinstance(credentials, list)

    source_endpoints: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)
    for raw in endpoints:
        assert isinstance(raw, dict)
        source_endpoints[
            str(raw["device_id"])
        ].append(raw)

    for raw in devices:
        assert isinstance(raw, dict)
        item = raw
        source_uuid = service._source_uuid(
            item
        )
        source_id = str(source_uuid)
        target = match_existing_device(
            session, item=item, source_uuid=source_uuid,
            source_endpoints=source_endpoints,
        )

        if target is None:
            skipped.append(
                service._apply_item(
                    section="devices",
                    resource_type="device",
                    item=item,
                    action="skipped",
                    reason=(
                        "credentials_required"
                    ),
                )
            )
            continue

        if (
            str(item.get("adapter_type"))
            != target.adapter_type
        ):
            skipped.append(
                service._apply_item(
                    section="devices",
                    resource_type="device",
                    item=item,
                    action="skipped",
                    target_id=target.id,
                    reason=(
                        "adapter_type_mismatch"
                    ),
                )
            )
            continue

        target.name = str(
            item["name"]
        )
        for field in (
            "manufacturer",
            "model",
            "serial_number",
            "hardware_id",
        ):
            value = item.get(field)
            setattr(
                target,
                field,
                (
                    str(value)
                    if value is not None
                    else None
                ),
            )
        target.capabilities_json = dict(
            item.get("capabilities")
            or {}
        )
        session.flush()
        device_map[source_id] = target.id
        applied.append(
            service._apply_item(
                section="devices",
                resource_type="device",
                item=item,
                action="updated",
                target_id=target.id,
            )
        )

    for raw in endpoints:
        assert isinstance(raw, dict)
        item = raw
        skipped.append(
            service._apply_item(
                section="devices",
                resource_type="device_endpoint",
                item=item,
                action="skipped",
                reason=(
                    "endpoint_address_preserved"
                ),
            )
        )
    for raw in credentials:
        assert isinstance(raw, dict)
        item = raw
        skipped.append(
            service._apply_item(
                section="devices",
                resource_type="device_credential",
                item=item,
                action="skipped",
                reason="credential_required",
            )
        )
