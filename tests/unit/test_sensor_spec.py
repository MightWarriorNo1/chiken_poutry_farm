"""SensorSpec parses EdgeConfig sensor entries into typed runtime objects."""

from __future__ import annotations

import pytest

from edge.domain.reading import SensorType
from edge.sensors.spec import DEFAULT_UNITS, SensorSpec


def test_from_config_minimal() -> None:
    spec = SensorSpec.from_config(
        {
            "sensor_id": "t1",
            "sensor_type": "temperature",
            "source": {"protocol": "mqtt", "topic": "p/t1"},
        }
    )
    assert spec.sensor_id == "t1"
    assert spec.sensor_type == SensorType.TEMPERATURE
    assert spec.unit == DEFAULT_UNITS[SensorType.TEMPERATURE]
    assert spec.protocol == "mqtt"
    assert spec.source["topic"] == "p/t1"


def test_from_config_with_explicit_unit_and_zone() -> None:
    spec = SensorSpec.from_config(
        {
            "sensor_id": "h1",
            "sensor_type": "humidity",
            "unit": "ratio",
            "shed_id": "shed-A",
            "zone_id": "zone-1",
            "source": {"protocol": "simulator"},
        }
    )
    assert spec.unit == "ratio"
    assert spec.shed_id == "shed-A"
    assert spec.zone_id == "zone-1"


def test_protocol_defaults_to_unknown_when_absent() -> None:
    spec = SensorSpec.from_config(
        {"sensor_id": "x", "sensor_type": "co2"}
    )
    assert spec.protocol == "unknown"


def test_invalid_sensor_type_raises() -> None:
    with pytest.raises(ValueError):
        SensorSpec.from_config({"sensor_id": "x", "sensor_type": "not_a_real_type"})
