"""Factory: protocol + sensor configs → SensorReader adapter.

Adding a new protocol (e.g. BACnet, OPC-UA) is a one-branch change here.
"""

from __future__ import annotations

from typing import Any

from edge.config import ModbusSettings, MqttSettings
from edge.sensors.modbus_reader import ModbusSensorReader
from edge.sensors.mqtt_reader import MqttSensorReader
from edge.sensors.sensor import SensorReader
from edge.sensors.simulator import SimulatedSensorReader
from edge.sensors.spec import SensorSpec


def build_sensor_reader(
    protocol: str,
    sensor_configs: list[dict[str, Any]],
    *,
    device_id: str,
    mqtt: MqttSettings,
    modbus: ModbusSettings,
) -> SensorReader:
    """Return the right adapter for `protocol`, populated with the given sensors."""
    specs = [SensorSpec.from_config(c) for c in sensor_configs]

    if protocol == "simulator":
        return SimulatedSensorReader(device_id=device_id, sensors=specs)

    if protocol == "mqtt":
        return MqttSensorReader(device_id=device_id, broker=mqtt, sensors=specs)

    if protocol == "modbus":
        return ModbusSensorReader(device_id=device_id, sensors=specs, settings=modbus)

    raise ValueError(f"Unsupported sensor protocol: {protocol!r}")
