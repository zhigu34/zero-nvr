from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.integrations.zlm import ZlmContinuityTracker


VHOST = "__defaultVhost__"
APP = "zero-nvr"
STREAM = "profile-11111111111111111111111111111111"


def at(second: int) -> datetime:
    return datetime(2026, 9, 20, 0, 0, second, tzinfo=UTC)


def test_late_old_hook_keeps_old_generation_segment_memory() -> None:
    tracker = ZlmContinuityTracker()

    old_generation = tracker.registered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(0),
    )
    old_segment = uuid.uuid4()
    assert tracker.remember_segment(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        continuity_id=old_generation,
        segment_id=old_segment,
        started_at=at(1),
    )

    closed = tracker.unregistered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(10),
    )
    assert closed == old_generation

    new_generation = tracker.registered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(12),
    )
    assert new_generation != old_generation

    new_segment = uuid.uuid4()
    assert tracker.remember_segment(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        continuity_id=new_generation,
        segment_id=new_segment,
        started_at=at(13),
    )

    late_old = tracker.resolve_record(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        started_at=at(9),
    )
    assert late_old is not None
    assert late_old.continuity_id == old_generation
    assert late_old.previous_segment_id == old_segment
    assert late_old.opened_at == at(0)
    assert late_old.closed_at == at(10)

    current = tracker.resolve_record(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        started_at=at(13),
    )
    assert current is not None
    assert current.continuity_id == new_generation
    assert current.previous_segment_id == new_segment
    assert current.opened_at == at(12)
    assert current.closed_at is None


def test_hook_in_disconnect_gap_has_no_proven_continuity() -> None:
    tracker = ZlmContinuityTracker()

    tracker.registered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(0),
    )
    tracker.unregistered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(10),
    )
    tracker.registered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(12),
    )

    # A file whose start evidence falls after old unregister but before the new
    # register is not safely attributable to either generation.
    assert tracker.resolve_record(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        started_at=at(11),
    ) is None


def test_duplicate_register_keeps_generation_and_last_segment() -> None:
    tracker = ZlmContinuityTracker()

    generation = tracker.registered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(0),
    )
    segment_id = uuid.uuid4()
    assert tracker.remember_segment(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        continuity_id=generation,
        segment_id=segment_id,
    )

    repeated = tracker.registered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(1),
    )
    assert repeated == generation

    resolved = tracker.resolve_record(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        started_at=at(2),
    )
    assert resolved is not None
    assert resolved.continuity_id == generation
    assert resolved.previous_segment_id == segment_id


def test_unknown_generation_cannot_replace_active_segment_memory() -> None:
    tracker = ZlmContinuityTracker()
    generation = tracker.registered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(0),
    )

    real_segment = uuid.uuid4()
    assert tracker.remember_segment(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        continuity_id=generation,
        segment_id=real_segment,
    )

    assert tracker.remember_segment(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        continuity_id=uuid.uuid4(),
        segment_id=uuid.uuid4(),
    ) is False

    resolved = tracker.resolve_record(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        started_at=at(3),
    )
    assert resolved is not None
    assert resolved.previous_segment_id == real_segment



def test_out_of_order_closed_hook_cannot_move_tail_backwards() -> None:
    tracker = ZlmContinuityTracker()
    generation = tracker.registered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(0),
    )

    newest = uuid.uuid4()
    assert tracker.remember_segment(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        continuity_id=generation,
        segment_id=newest,
        started_at=at(8),
    )
    tracker.unregistered(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        at=at(10),
    )

    older = uuid.uuid4()
    assert tracker.remember_segment(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        continuity_id=generation,
        segment_id=older,
        started_at=at(5),
    ) is False

    resolved = tracker.resolve_record(
        vhost=VHOST,
        app=APP,
        stream=STREAM,
        started_at=at(9),
    )
    assert resolved is not None
    assert resolved.previous_segment_id == newest
    assert resolved.opened_at == at(0)
    assert resolved.closed_at == at(10)
