"""ProjectingOutbox: forwards puts, tees to read model + event bus."""

from __future__ import annotations

import pytest

from edge.dashboard.event_bus import EventBus
from edge.dashboard.projecting_outbox import ProjectingOutbox
from edge.domain.events import EventEnvelope, EventType


class _RecordingInner:
    def __init__(self) -> None:
        self.puts: list[EventEnvelope] = []
        self.inited = False
        self.closed = False

    async def init(self) -> None:
        self.inited = True

    async def close(self) -> None:
        self.closed = True

    async def put(self, event: EventEnvelope) -> None:
        self.puts.append(event)

    async def peek(self, *_a, **_kw):
        return []

    async def ack(self, _ids):
        pass

    async def nack(self, _ids):
        pass

    async def pending_count(self) -> int:
        return len(self.puts)


class _RecordingReadModel:
    def __init__(self) -> None:
        self.applied: list[EventEnvelope] = []

    async def init(self) -> None: ...
    async def close(self) -> None: ...
    async def apply(self, event: EventEnvelope) -> None:
        self.applied.append(event)


@pytest.mark.asyncio
async def test_put_writes_through_then_projects() -> None:
    inner = _RecordingInner()
    rm = _RecordingReadModel()
    bus = EventBus(max_queue=8)
    wrapper = ProjectingOutbox(inner=inner, read_model=rm, event_bus=bus)

    seen: list[EventEnvelope] = []
    async with bus.subscribe() as recv:
        env = EventEnvelope(event_type=EventType.SENSOR_READING, payload={"v": 1})
        await wrapper.put(env)
        # Pull one frame off the bus without blocking on a non-arriving second.
        seen.append(await recv.receive())

    assert inner.puts == [env]
    assert rm.applied == [env]
    assert seen == [env]


@pytest.mark.asyncio
async def test_projection_exception_does_not_break_put() -> None:
    inner = _RecordingInner()

    class BoomReadModel:
        async def apply(self, _ev):
            raise RuntimeError("kaboom")
        async def init(self): ...
        async def close(self): ...

    bus = EventBus()
    wrapper = ProjectingOutbox(inner=inner, read_model=BoomReadModel(), event_bus=bus)

    env = EventEnvelope(event_type=EventType.BIRD_DETECTION, payload={})
    # Must not raise.
    await wrapper.put(env)
    assert inner.puts == [env]


@pytest.mark.asyncio
async def test_passthrough_methods() -> None:
    inner = _RecordingInner()
    wrapper = ProjectingOutbox(
        inner=inner,
        read_model=_RecordingReadModel(),
        event_bus=EventBus(),
    )

    await wrapper.init()
    assert inner.inited
    pending = await wrapper.pending_count()
    assert pending == 0
    await wrapper.close()
    assert inner.closed
