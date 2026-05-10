"""Synthetic sensor reader for offline development.

Emits realistic-ish poultry-shed readings: 24°C ± diurnal swing, 65% RH ± noise,
optional ammonia trickle. No external broker required.
"""

from __future__ import annotations

import math
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone

import anyio

from edge.domain.reading import SensorReading, SensorType


@dataclass(frozen=True, slots=True)
class SimulatedSensor:
    sensor_id: str
    sensor_type: SensorType
    unit: str
    base: float
    swing: float
    noise: float
    shed_id: str | None = None
    zone_id: str | None = None


DEFAULT_SENSORS: tuple[SimulatedSensor, ...] = (
    SimulatedSensor("sim-temp-1", SensorType.TEMPERATURE, "celsius", 24.0, 3.0, 0.3),
    SimulatedSensor("sim-hum-1", SensorType.HUMIDITY, "percent", 65.0, 5.0, 1.5),
    SimulatedSensor("sim-nh3-1", SensorType.AMMONIA, "ppm", 8.0, 2.0, 0.5),
)


class SimulatedSensorReader:
    def __init__(
        self,
        device_id: str,
        sensors: tuple[SimulatedSensor, ...] = DEFAULT_SENSORS,
        period_seconds: float = 5.0,
    ) -> None:
        self._device_id = device_id
        self._sensors = sensors
        self._period = period_seconds
        self._stop = anyio.Event()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self._stop.set()

    async def readings(self) -> AsyncIterator[SensorReading]:
        t = 0.0
        while not self._stop.is_set():
            for s in self._sensors:
                value = (
                    s.base
                    + s.swing * math.sin(2 * math.pi * t / 600.0)  # 10-min diurnal cycle
                    + random.uniform(-s.noise, s.noise)             # noqa: S311
                )
                yield SensorReading(
                    device_id=self._device_id,
                    sensor_id=s.sensor_id,
                    sensor_type=s.sensor_type,
                    shed_id=s.shed_id,
                    zone_id=s.zone_id,
                    value=round(value, 3),
                    unit=s.unit,
                    recorded_at=datetime.now(timezone.utc),
                )
            t += self._period
            with anyio.move_on_after(self._period):
                await self._stop.wait()
