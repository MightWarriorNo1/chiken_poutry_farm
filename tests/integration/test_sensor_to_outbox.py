"""End-to-end: simulator → SensorPipeline → SqliteOutbox."""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from edge.domain.events import EventType
from edge.outbox.sqlite_outbox import SqliteOutbox
from edge.pipelines.sensor_pipeline import SensorPipeline
from edge.sensors.simulator import SimulatedSensorReader


@pytest.mark.integration
@pytest.mark.asyncio
async def test_simulator_drains_into_outbox(tmp_path: Path) -> None:
    outbox = SqliteOutbox(tmp_path / "ob.db")
    await outbox.init()

    reader = SimulatedSensorReader(device_id="edge-1", period_seconds=0.01)
    pipe = SensorPipeline(reader=reader, outbox=outbox)

    async with anyio.create_task_group() as tg:
        tg.start_soon(pipe.run)
        await anyio.sleep(0.5)
        tg.cancel_scope.cancel()

    pending = await outbox.peek(EventType.SENSOR_READING, 100)
    assert len(pending) >= 3
    await outbox.close()
