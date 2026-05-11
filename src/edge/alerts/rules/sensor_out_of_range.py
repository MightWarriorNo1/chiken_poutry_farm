"""Sensor out-of-range rule.

Reads thresholds from the EdgeConfig.sensors[*].thresholds block. Call
`update_sensors(sensors_cfg)` whenever the config changes (the wiring in
`main.py` does this from the ConfigPipeline).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from edge.alerts.rule import RaisedTracker
from edge.domain.alert import Alert, AlertSeverity, AlertSource, AlertType
from edge.domain.events import EventEnvelope, EventType


@dataclass(slots=True)
class _Spec:
    sensor_type: str | None
    shed_id: str | None
    zone_id: str | None
    min: float | None
    max: float | None


class SensorOutOfRangeRule:
    name = "sensor_out_of_range"

    def __init__(
        self,
        device_id: str,
        sensor_configs: list[dict[str, Any]] | None = None,
        cooldown_seconds: float = 300.0,
    ) -> None:
        self._device_id = device_id
        self._tracker = RaisedTracker(cooldown_seconds)
        self._specs: dict[str, _Spec] = {}
        if sensor_configs:
            self.update_sensors(sensor_configs)

    def update_sensors(self, sensor_configs: list[dict[str, Any]]) -> None:
        new: dict[str, _Spec] = {}
        for cfg in sensor_configs:
            sensor_id = cfg.get("sensor_id")
            thresholds = cfg.get("thresholds")
            if not sensor_id or not thresholds:
                continue
            new[str(sensor_id)] = _Spec(
                sensor_type=cfg.get("sensor_type"),
                shed_id=cfg.get("shed_id"),
                zone_id=cfg.get("zone_id"),
                min=_to_float(thresholds.get("min")),
                max=_to_float(thresholds.get("max")),
            )
        self._specs = new

    async def on_event(self, event: EventEnvelope) -> Sequence[Alert]:
        if event.event_type != EventType.SENSOR_READING:
            return []
        payload = event.payload
        sensor_id = payload.get("sensor_id")
        spec = self._specs.get(str(sensor_id)) if sensor_id else None
        if spec is None:
            return []
        value = payload.get("value")
        if not isinstance(value, (int, float)):
            return []

        direction = self._breach(value, spec)
        key = self._key(str(sensor_id))
        if direction is None:
            self._tracker.reset(key)
            return []

        now = datetime.now(timezone.utc)
        if not self._tracker.should_raise(key, now):
            return []

        unit = payload.get("unit", "")
        sensor_type = spec.sensor_type or "sensor"
        return [
            Alert(
                device_id=self._device_id,
                alert_type=AlertType.SENSOR_OUT_OF_RANGE,
                severity=AlertSeverity.HIGH if direction == "high" else AlertSeverity.MEDIUM,
                source=AlertSource.SENSOR,
                sensor_id=str(sensor_id),
                shed_id=spec.shed_id,
                zone_id=spec.zone_id,
                raised_at=now,
                message=(
                    f"{sensor_type} {sensor_id} reading {value}{unit} is "
                    f"{direction} (range {spec.min}–{spec.max})."
                ),
                correlation_key=key,
                metrics={
                    "value": value,
                    "unit": unit,
                    "min": spec.min,
                    "max": spec.max,
                    "direction": direction,
                },
            )
        ]

    async def tick(self, _now: datetime) -> Sequence[Alert]:
        return []

    # ── private ───────────────────────────────────────────────────────────
    @staticmethod
    def _breach(value: float, spec: _Spec) -> str | None:
        if spec.min is not None and value < spec.min:
            return "low"
        if spec.max is not None and value > spec.max:
            return "high"
        return None

    @classmethod
    def _key(cls, sensor_id: str) -> str:
        return f"{cls.name}:{sensor_id}"


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
