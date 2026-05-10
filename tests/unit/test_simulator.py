"""Sensor simulator emits well-formed readings."""

from __future__ import annotations

import anyio
import pytest

from edge.domain.reading import SensorReading
from edge.sensors.simulator import SimulatedSensorReader


@pytest.mark.asyncio
async def test_simulator_emits_readings() -> None:
    reader = SimulatedSensorReader(device_id="edge-1", period_seconds=0.01)
    await reader.start()
    collected: list[SensorReading] = []

    async def collect() -> None:
        async for reading in reader.readings():
            collected.append(reading)
            if len(collected) >= 6:
                await reader.stop()
                return

    with anyio.move_on_after(2.0):
        await collect()

    assert len(collected) >= 3
    assert all(r.device_id == "edge-1" for r in collected)
    assert all(r.value is not None for r in collected)
