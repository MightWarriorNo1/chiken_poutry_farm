"""EventBus: multi-subscriber fan-out, slow-subscriber drop semantics."""

from __future__ import annotations

import anyio
import pytest

from edge.dashboard.event_bus import EventBus
from edge.domain.events import EventEnvelope, EventType


def _make(n: int) -> EventEnvelope:
    return EventEnvelope(event_type=EventType.SENSOR_READING, payload={"n": n})


@pytest.mark.asyncio
async def test_publish_fans_out_to_all_subscribers() -> None:
    bus = EventBus()
    async with bus.subscribe() as a, bus.subscribe() as b:
        env = _make(1)
        await bus.publish(env)
        ra = await a.receive()
        rb = await b.receive()
        assert ra.payload == {"n": 1}
        assert rb.payload == {"n": 1}


@pytest.mark.asyncio
async def test_slow_subscriber_drops_oldest_not_publisher_block() -> None:
    bus = EventBus(max_queue=2)
    async with bus.subscribe() as recv:
        # Publish more than the queue depth; later events are dropped for this
        # subscriber but publish does not block.
        for i in range(5):
            await bus.publish(_make(i))

        # We only get the first 2 (the ones that fit before WouldBlock).
        received: list[int] = []
        with anyio.move_on_after(0.05):
            while True:
                ev = await recv.receive()
                received.append(ev.payload["n"])

        assert received == [0, 1]


@pytest.mark.asyncio
async def test_unsubscribe_removes_from_fanout() -> None:
    bus = EventBus()
    async with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_is_safe() -> None:
    bus = EventBus()
    await bus.publish(_make(99))  # must not raise
    assert bus.subscriber_count == 0
