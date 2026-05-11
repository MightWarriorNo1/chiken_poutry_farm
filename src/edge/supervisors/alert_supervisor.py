"""AlertSupervisor — pushes EdgeConfig changes into stateful alert rules.

Most rules are stateless or self-configuring. The exception is
`SensorOutOfRangeRule`, which needs sensor thresholds. This supervisor reads
`EdgeConfig.sensors[*]` and forwards thresholds into the rule on every config
apply. Adding a future config-driven rule is a one-line change here.
"""

from __future__ import annotations

from typing import Any

import structlog

from edge.alerts.rules.sensor_out_of_range import SensorOutOfRangeRule

log = structlog.get_logger(__name__)


class AlertSupervisor:
    def __init__(
        self,
        sensor_out_of_range: SensorOutOfRangeRule | None = None,
    ) -> None:
        self._sensor_rule = sensor_out_of_range

    async def apply(self, config: dict[str, Any]) -> None:
        if self._sensor_rule is not None:
            sensors = config.get("sensors") or []
            self._sensor_rule.update_sensors(sensors)
            log.info(
                "alerts.sensor_thresholds_updated",
                sensors_with_thresholds=sum(1 for s in sensors if s.get("thresholds")),
            )
