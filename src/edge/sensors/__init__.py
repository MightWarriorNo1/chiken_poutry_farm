"""IoT sensor ingestion: ports + protocol adapters + factory."""

from edge.sensors.factory import build_sensor_reader
from edge.sensors.sensor import SensorReader
from edge.sensors.spec import DEFAULT_UNITS, SensorSpec

__all__ = ["DEFAULT_UNITS", "SensorReader", "SensorSpec", "build_sensor_reader"]
