from __future__ import annotations

import pytest

from app.core.events import RuntimeEventBus


@pytest.mark.asyncio
async def test_runtime_event_bus_is_bounded_and_drops_old_hints() -> None:
    bus = RuntimeEventBus(queue_size=4)
    queue = await bus.subscribe()

    for index in range(5):
        await bus.publish(
            "api.mutation",
            {
                "method": "PATCH",
                "path": f"/api/v1/example/{index}",
            },
        )

    assert queue.qsize() == 4
    events = [
        queue.get_nowait()
        for _ in range(4)
    ]
    assert [event["id"] for event in events] == [
        2,
        3,
        4,
        5,
    ]
    assert events[-1]["data"] == {
        "method": "PATCH",
        "path": "/api/v1/example/4",
    }

    await bus.unsubscribe(queue)
    await bus.publish(
        "api.mutation",
        {"method": "POST", "path": "/api/v1/after"},
    )
    assert queue.empty()
