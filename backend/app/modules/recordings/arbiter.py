from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from .models import RecordingPolicy
from .policy import RecordingPolicyService
from .triggers import RecordingTriggerService


ArbitratedRecorderMode = Literal[
    "persistent",
    "prebuffer",
    "off",
]


@dataclass(frozen=True, slots=True)
class RecordingArbitrationDecision:
    mode: ArbitratedRecorderMode
    reasons: tuple[str, ...]
    baseline_active: bool
    event_active: bool
    manual_active: bool


class RecordingArbiterService:
    """Derive one camera recorder requirement from durable product facts."""

    @classmethod
    def evaluate(
        cls,
        session: Session,
        *,
        camera_id: uuid.UUID,
        camera_enabled: bool,
        policy: RecordingPolicy,
        at: datetime | None = None,
    ) -> RecordingArbitrationDecision:
        instant = (
            at or datetime.now(UTC)
        ).astimezone(UTC)

        if not camera_enabled or not policy.enabled:
            return RecordingArbitrationDecision(
                mode="off",
                reasons=(),
                baseline_active=False,
                event_active=False,
                manual_active=False,
            )

        baseline_active = (
            RecordingPolicyService
            .baseline_should_record(
                policy,
                at=instant,
            )
        )
        active_triggers = (
            RecordingTriggerService.active_at(
                session,
                camera_id=camera_id,
                at=instant,
            )
        )
        manual_active = any(
            trigger.type.upper() == "MANUAL"
            for trigger in active_triggers
        )
        event_active = (
            policy.event_recording_enabled
            and any(
                trigger.type.upper()
                != "MANUAL"
                for trigger in active_triggers
            )
        )

        reasons: list[str] = []
        if baseline_active:
            reasons.append(
                "continuous"
                if policy.baseline_mode
                == "continuous"
                else "schedule"
            )
        if event_active:
            reasons.append("event")
        if manual_active:
            reasons.append("manual")

        if baseline_active or manual_active:
            mode: ArbitratedRecorderMode = (
                "persistent"
            )
        elif policy.event_recording_enabled:
            mode = "prebuffer"
        else:
            mode = "off"

        return RecordingArbitrationDecision(
            mode=mode,
            reasons=tuple(reasons),
            baseline_active=baseline_active,
            event_active=event_active,
            manual_active=manual_active,
        )
