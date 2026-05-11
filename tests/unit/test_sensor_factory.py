"""build_sensor_reader dispatches on protocol."""

from __future__ import annotations

import pytest

from edge.config import ModbusSettings, MqttSettings
from edge.sensors.factory import build_sensor_reader
from edge.sensors.modbus_reader import ModbusSensorReader
from edge.sensors.mqtt_reader import MqttSensorReader
from edge.sensors.simulator import SimulatedSensorReader


def _kwargs() -> dict:
    return {
        "device_id": "edge-1",
        "mqtt": MqttSettings(),
        "modbus": ModbusSettings(),
    }


def test_simulator_protocol_returns_simulator() -> None:
    reader = build_sensor_reader(
        "simulator",
        [{"sensor_id": "s1", "sensor_type": "temperature", "source": {"protocol": "simulator"}}],
        **_kwargs(),
    )
    assert isinstance(reader, SimulatedSensorReader)


def test_mqtt_protocol_returns_mqtt_reader() -> None:
    reader = build_sensor_reader(
        "mqtt",
        [
            {
                "sensor_id": "t1",
                "sensor_type": "temperature",
                "source": {"protocol": "mqtt", "topic": "p/t1"},
            }
        ],
        **_kwargs(),
    )
    assert isinstance(reader, MqttSensorReader)
    assert "p/t1" in reader.topics


def test_modbus_protocol_returns_modbus_reader() -> None:
    reader = build_sensor_reader(
        "modbus",
        [
            {
                "sensor_id": "m1",
                "sensor_type": "temperature",
                "source": {"protocol": "modbus", "register": 100},
            }
        ],
        **_kwargs(),
    )
    assert isinstance(reader, ModbusSensorReader)


def test_unknown_protocol_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported sensor protocol"):
        build_sensor_reader("opcua", [], **_kwargs())
