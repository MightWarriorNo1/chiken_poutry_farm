"""Synthetic sensor reader for offline development.

Emits realistic-ish poultry-shed readings — diurnal swing + Gaussian noise on
each sensor type — without needing any external broker or hardware.
"""

from __future__ import annotations

import math
import random
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone

import anyio

from edge.domain.reading import SensorReading, SensorType
from edge.sensors.spec import DEFAULT_UNITS, SensorSpec

# (base, swing, noise) per sensor type. Swing is the diurnal-cycle amplitude.
_PROFILES: dict[SensorType, tuple[float, float, float]] = {
    SensorType.TEMPERATURE: (24.0, 3.0, 0.3),
    SensorType.HUMIDITY: (65.0, 5.0, 1.5),
    SensorType.AMMONIA: (8.0, 2.0, 0.5),
    SensorType.CO2: (1500.0, 200.0, 50.0),
    SensorType.WATER_FLOW: (4.5, 1.0, 0.2),
    SensorType.WATER_PRESSURE: (2.0, 0.3, 0.05),
}

# Default sensor set used when no specs are supplied — keeps the simulator
# usable as a one-line drop-in for demos and the existing unit test.
DEFAULT_SENSORS: tuple[SensorSpec, ...] = (
    SensorSpec("sim-temp-1", SensorType.TEMPERATURE, "celsius"),
    SensorSpec("sim-hum-1", SensorType.HUMIDITY, "percent"),
    SensorSpec("sim-nh3-1", SensorType.AMMONIA, "ppm"),
)


class SimulatedSensorReader:
    def __init__(
        self,
        device_id: str,
        sensors: Sequence[SensorSpec] | None = None,
        period_seconds: float = 5.0,
    ) -> None:
        self._device_id = device_id
        self._sensors: tuple[SensorSpec, ...] = tuple(sensors) if sensors else DEFAULT_SENSORS
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
                profile = _PROFILES.get(s.sensor_type)
                if profile is None:
                    continue
                base, swing, noise = profile
                value = (
                    base
                    + swing * math.sin(2 * math.pi * t / 600.0)  # 10-min diurnal cycle
                    + random.uniform(-noise, noise)              # noqa: S311
                )
                yield SensorReading(
                    device_id=self._device_id,
                    sensor_id=s.sensor_id,
                    sensor_type=s.sensor_type,
                    shed_id=s.shed_id,
                    zone_id=s.zone_id,
                    value=round(value, 3),
                    unit=s.unit or DEFAULT_UNITS.get(s.sensor_type, ""),
                    recorded_at=datetime.now(timezone.utc),
                )
            t += self._period
            with anyio.move_on_after(self._period):
                await self._stop.wait()
