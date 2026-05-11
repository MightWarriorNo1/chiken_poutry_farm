"""IoT sensor readings."""

from __future__ import annotations

from datetime import datetime
from edge._compat import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class SensorType(StrEnum):
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    AMMONIA = "ammonia"
    CO2 = "co2"
    WATER_FLOW = "water_flow"
    WATER_PRESSURE = "water_pressure"


class SensorQuality(StrEnum):
    GOOD = "good"
    SUSPECT = "suspect"
    BAD = "bad"


class SensorReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    device_id: str
    sensor_id: str
    sensor_type: SensorType
    shed_id: str | None = None
    zone_id: str | None = None
    value: float
    unit: str
    recorded_at: datetime
    quality: SensorQuality = SensorQuality.GOOD
