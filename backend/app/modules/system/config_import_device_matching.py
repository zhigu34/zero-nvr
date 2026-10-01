"""Resolve exported device IDs against existing local devices."""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.cameras.models import Device, DeviceEndpoint


def match_existing_device(
    session: Session,
    *,
    item: dict[str, Any],
    source_uuid: uuid.UUID,
    source_endpoints: dict[str, list[dict[str, Any]]],
) -> Device | None:
    source_id = str(source_uuid)
    target = session.get(
        Device,
        source_uuid,
    )

    if target is None:
        hardware_id = item.get(
            "hardware_id"
        )
        if (
            isinstance(hardware_id, str)
            and hardware_id
        ):
            matches = list(
                session.scalars(
                    select(Device).where(
                        Device.hardware_id
                        == hardware_id
                    )
                )
            )
            if len(matches) == 1:
                target = matches[0]

    if (
        target is None
        and item.get("adapter_type")
        == "manual_rtsp"
    ):
        candidates: set[
            uuid.UUID
        ] = set()
        for endpoint in (
            source_endpoints.get(
                source_id,
                [],
            )
        ):
            host = endpoint.get("host")
            endpoint_type = (
                endpoint.get("type")
            )
            port = endpoint.get("port")
            if (
                not isinstance(host, str)
                or not isinstance(
                    endpoint_type,
                    str,
                )
            ):
                continue
            statement = (
                select(DeviceEndpoint)
                .where(
                    DeviceEndpoint.type
                    == endpoint_type,
                    DeviceEndpoint.host
                    == host,
                )
            )
            if port is None:
                statement = (
                    statement.where(
                        DeviceEndpoint.port
                        .is_(None)
                    )
                )
            else:
                statement = (
                    statement.where(
                        DeviceEndpoint.port
                        == port
                    )
                )
            for found in (
                session.scalars(
                    statement
                )
            ):
                device = session.get(
                    Device,
                    found.device_id,
                )
                if (
                    device is not None
                    and device.adapter_type
                    == "manual_rtsp"
                ):
                    candidates.add(
                        device.id
                    )
        if len(candidates) == 1:
            target = session.get(
                Device,
                next(
                    iter(candidates)
                ),
            )

    return target
