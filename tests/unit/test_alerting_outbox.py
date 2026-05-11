"""AlertingOutbox — transparently forwards Outbox methods + fires engine."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import pytest

from edge.alerts.alerting_outbox import AlertingOutbox
from edge.alerts.engine import AlertEngine
from edge.domain.events import EventEnvelope, EventType


class _RecordingInner:
    def __init__(self) -> None:
        self.puts: list[EventEnvelope] = []
        self.acks: list[Sequence[UUID]] = []
        self.nacks: list[Sequence[UUID]] = []
        self.inited = False
        self.closed = False

    async def init(self) -> None:
        self.inited = True

    async def close(self) -> None:
        self.closed = True

    async def put(self, event: EventEnvelope) -> None:
        self.puts.append(event)

    async def peek(self, event_type, limit):
        return [e for e in self.puts if e.event_type == event_type][:limit]

    async def ack(self, ids):
        self.acks.append(list(ids))

    async def nack(self, ids):
        self.nacks.append(list(ids))

    async def pending_count(self):
        return len(self.puts)


@pytest.mark.asyncio
async def test_put_writes_through_and_fires_engine() -> None:
    inner = _RecordingInner()
    seen: list[EventEnvelope] = []

    class CapturingRule:
        name = "cap"

        async def on_event(self, ev):
            seen.append(ev)
            return []

        async def tick(self, _now):
            return []

    engine = AlertEngine(outbox=inner, rules=[CapturingRule()])
    wrapper = AlertingOutbox(inner=inner, engine=engine)

    env = EventEnvelope(event_type=EventType.SENSOR_READING, payload={"value": 1})
    await wrapper.put(env)

    assert inner.puts == [env]
    assert seen == [env]


@pytest.mark.asyncio
async def test_other_methods_pass_through() -> None:
    inner = _RecordingInner()
    engine = AlertEngine(outbox=inner, rules=[])
    wrapper = AlertingOutbox(inner=inner, engine=engine)

    await wrapper.init()
    await wrapper.put(EventEnvelope(event_type=EventType.SENSOR_READING, payload={}))
    await wrapper.ack([UUID(int=1)])
    await wrapper.nack([UUID(int=2)])
    pending = await wrapper.pending_count()
    await wrapper.close()

    assert inner.inited and inner.closed
    assert inner.acks == [[UUID(int=1)]]
    assert inner.nacks == [[UUID(int=2)]]
    assert pending == 1


@pytest.mark.asyncio
async def test_engine_exception_does_not_break_put() -> None:
    inner = _RecordingInner()

    class BoomEngine:
        async def on_event(self, _ev):
            raise RuntimeError("engine exploded")

    wrapper = AlertingOutbox(inner=inner, engine=BoomEngine())
    env = EventEnvelope(event_type=EventType.SENSOR_READING, payload={})
    # Must not raise.
    await wrapper.put(env)
    assert inner.puts == [env]
