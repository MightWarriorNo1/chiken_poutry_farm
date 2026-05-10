"""SQLite outbox: durability + FIFO."""

from __future__ import annotations

from pathlib import Path

import pytest

from edge.domain.events import EventEnvelope, EventType
from edge.outbox.sqlite_outbox import SqliteOutbox


@pytest.mark.asyncio
async def test_put_peek_ack_cycle(tmp_path: Path) -> None:
    outbox = SqliteOutbox(tmp_path / "ob.db")
    await outbox.init()
    try:
        for i in range(3):
            await outbox.put(
                EventEnvelope(
                    event_type=EventType.SENSOR_READING,
                    payload={"value": i},
                )
            )

        assert await outbox.pending_count() == 3

        batch = await outbox.peek(EventType.SENSOR_READING, 10)
        assert len(batch) == 3
        assert [e.payload["value"] for e in batch] == [0, 1, 2]

        await outbox.ack([e.event_id for e in batch])
        assert await outbox.pending_count() == 0
    finally:
        await outbox.close()


@pytest.mark.asyncio
async def test_nack_increments_attempts(tmp_path: Path) -> None:
    outbox = SqliteOutbox(tmp_path / "ob.db")
    await outbox.init()
    try:
        env = EventEnvelope(event_type=EventType.SENSOR_READING, payload={})
        await outbox.put(env)
        await outbox.nack([env.event_id])
        [reloaded] = await outbox.peek(EventType.SENSOR_READING, 1)
        assert reloaded.attempts == 1
    finally:
        await outbox.close()


@pytest.mark.asyncio
async def test_per_type_isolation(tmp_path: Path) -> None:
    outbox = SqliteOutbox(tmp_path / "ob.db")
    await outbox.init()
    try:
        await outbox.put(EventEnvelope(event_type=EventType.SENSOR_READING, payload={}))
        await outbox.put(EventEnvelope(event_type=EventType.BIRD_DETECTION, payload={}))
        sensors = await outbox.peek(EventType.SENSOR_READING, 10)
        detections = await outbox.peek(EventType.BIRD_DETECTION, 10)
        assert len(sensors) == 1
        assert len(detections) == 1
    finally:
        await outbox.close()
