"""SensorSpec — runtime representation of one sensor from `EdgeConfig.sensors[*]`.

Adapters consume specs; SensorSupervisor groups specs by protocol and hands each
group to the right reader. The `source` dict holds protocol-specific parameters
(MQTT topic, Modbus register, etc.) — kept open-ended on purpose so adding a new
protocol doesn't require a domain change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edge.domain.reading import SensorType

# Default unit per sensor type — used when neither config nor payload supplies one.
DEFAULT_UNITS: dict[SensorType, str] = {
    SensorType.TEMPERATURE: "celsius",
    SensorType.HUMIDITY: "percent",
    SensorType.AMMONIA: "ppm",
    SensorType.CO2: "ppm",
    SensorType.WATER_FLOW: "lpm",
    SensorType.WATER_PRESSURE: "bar",
}


@dataclass(frozen=True, slots=True)
class SensorSpec:
    sensor_id: str
    sensor_type: SensorType
    unit: str = ""                            # filled from DEFAULT_UNITS if empty
    shed_id: str | None = None
    zone_id: str | None = None
    source: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> SensorSpec:
        sensor_type = SensorType(cfg["sensor_type"])
        unit = cfg.get("unit") or DEFAULT_UNITS.get(sensor_type, "")
        return cls(
            sensor_id=cfg["sensor_id"],
            sensor_type=sensor_type,
            unit=unit,
            shed_id=cfg.get("shed_id"),
            zone_id=cfg.get("zone_id"),
            source=dict(cfg.get("source") or {}),
        )

    @property
    def protocol(self) -> str:
        return str(self.source.get("protocol") or "unknown")
