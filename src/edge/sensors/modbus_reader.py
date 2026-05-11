"""Modbus TCP sensor reader.

Polls one or more holding registers per sensor at a fixed interval. Each
sensor's `source` block describes the register layout:

    sensors:
      - sensor_id: temp-1
        sensor_type: temperature
        unit: celsius
        source:
          protocol: modbus
          register: 100         # holding register address (required)
          count:    1           # number of 16-bit registers (default 1)
          unit_id:  1           # Modbus slave/unit id (default 1)
          scale:    0.1         # value = (raw +- offset) * scale
          offset:   0
          signed:   false       # interpret raw as signed 16-bit
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from typing import Any

import anyio
import structlog

from edge.config import ModbusSettings
from edge.domain.reading import SensorQuality, SensorReading
from edge.sensors.spec import SensorSpec

log = structlog.get_logger(__name__)


class ModbusSensorReader:
    def __init__(
        self,
        device_id: str,
        sensors: Sequence[SensorSpec],
        settings: ModbusSettings,
    ) -> None:
        self._device_id = device_id
        self._sensors = tuple(sensors)
        self._settings = settings
        self._client: Any | None = None
        self._stop = anyio.Event()

    async def start(self) -> None:
        try:
            from pymodbus.client import AsyncModbusTcpClient  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install the `sensors` extra: pip install -e '.[sensors]'"
            ) from exc

        client = AsyncModbusTcpClient(self._settings.host, port=self._settings.port)
        await client.connect()
        if not client.connected:
            raise ConnectionError(
                f"Modbus connect failed: {self._settings.host}:{self._settings.port}"
            )
        self._client = client
        log.info("modbus.started", host=self._settings.host, port=self._settings.port)

    async def stop(self) -> None:
        self._stop.set()
        if self._client is not None:
            self._client.close()
            self._client = None

    async def readings(self) -> AsyncIterator[SensorReading]:
        while not self._stop.is_set():
            for spec in self._sensors:
                value, quality = await self._read_one(spec)
                if value is None:
                    continue
                yield SensorReading(
                    device_id=self._device_id,
                    sensor_id=spec.sensor_id,
                    sensor_type=spec.sensor_type,
                    shed_id=spec.shed_id,
                    zone_id=spec.zone_id,
                    value=value,
                    unit=spec.unit,
                    recorded_at=datetime.now(timezone.utc),
                    quality=quality,
                )
            with anyio.move_on_after(self._settings.poll_interval_seconds):
                await self._stop.wait()

    # ── private ───────────────────────────────────────────────────────────
    async def _read_one(self, spec: SensorSpec) -> tuple[float | None, SensorQuality]:
        if self._client is None:
            return None, SensorQuality.BAD
        params = spec.source
        try:
            register = int(params["register"])
        except (KeyError, ValueError):
            log.warning("modbus.spec.missing_register", sensor=spec.sensor_id)
            return None, SensorQuality.BAD

        count = int(params.get("count", 1))
        unit_id = int(params.get("unit_id", 1))

        try:
            result = await self._client.read_holding_registers(register, count=count, slave=unit_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("modbus.read.failed", sensor=spec.sensor_id, error=str(exc))
            return None, SensorQuality.BAD
        if result.isError():
            log.warning("modbus.read.error", sensor=spec.sensor_id, result=str(result))
            return None, SensorQuality.BAD

        return self._decode(result.registers, params), SensorQuality.GOOD

    @staticmethod
    def _decode(registers: list[int], params: dict[str, Any]) -> float:
        """Decode raw 16-bit registers into a scaled float.

        Currently supports a single 16-bit register (signed or unsigned). 32-bit
        decoding (count=2) lands when the first device that needs it does.
        """
        raw = int(registers[0])
        if params.get("signed") and raw >= 0x8000:
            raw -= 0x10000
        scale = float(params.get("scale", 1.0))
        offset = float(params.get("offset", 0.0))
        return (raw + offset) * scale
