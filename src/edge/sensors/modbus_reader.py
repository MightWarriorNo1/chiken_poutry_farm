"""Modbus RTU/TCP sensor reader (placeholder).

Real implementations land alongside specific industrial sensors. Kept here so the
port wiring is in place for production deployments.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from edge.domain.reading import SensorReading


class ModbusSensorReader:
    async def start(self) -> None:
        raise NotImplementedError("Modbus support lands when a sensor model is selected.")

    async def stop(self) -> None: ...

    async def readings(self) -> AsyncIterator[SensorReading]:
        raise NotImplementedError
        yield  # pragma: no cover
