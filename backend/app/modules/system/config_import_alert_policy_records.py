"""Create or update one alert policy after dependencies are mapped."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.alerts.models import AlertPolicy
from app.modules.alerts.service import AlertPolicyService


def upsert_alert_policy(
    service: type,
    session: Session,
    *,
    item: dict[str, Any],
    match: dict[str, Any],
    actions: dict[str, Any],
) -> tuple[AlertPolicy, str]:
    source_uuid = service._source_uuid(
        item
    )
    target = session.get(
        AlertPolicy,
        source_uuid,
    )
    if target is None:
        target = (
            service._existing_by_name(
                session,
                AlertPolicy,
                str(item["name"]),
            )
        )
    if target is None:
        target = (
            AlertPolicyService.create(
                session,
                name=str(
                    item["name"]
                ),
                enabled=bool(
                    item["enabled"]
                ),
                severity=str(
                    item["severity"]
                ),
                match=match,
                actions=actions,
                cooldown_seconds=int(
                    item[
                        "cooldown_seconds"
                    ]
                ),
            )
        )
        action = "created"
    else:
        target = (
            AlertPolicyService.update(
                session,
                policy=target,
                changes={
                    "name": str(
                        item["name"]
                    ),
                    "enabled": bool(
                        item[
                            "enabled"
                        ]
                    ),
                    "severity": str(
                        item[
                            "severity"
                        ]
                    ),
                    "match": match,
                    "actions": actions,
                    "cooldown_seconds": int(
                        item[
                            "cooldown_seconds"
                        ]
                    ),
                },
            )
        )
        action = "updated"
    return target, action
