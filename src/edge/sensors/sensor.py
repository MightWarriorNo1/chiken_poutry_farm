"""Port: a source of sensor readings."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from edge.domain.reading import SensorReading


class SensorReader(Protocol):
    """Yields SensorReading events as they arrive (push) or are polled (pull)."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def readings(self) -> AsyncIterator[SensorReading]: ...
