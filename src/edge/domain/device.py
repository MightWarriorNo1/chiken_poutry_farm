"""Device telemetry: heartbeat + camera/sensor health snapshots."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CameraConnectionStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


class SensorConnectionStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class DeviceStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ERROR = "error"


class CameraStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera_id: str
    status: CameraConnectionStatus
    last_frame_at: datetime | None = None


class SensorStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_id: str
    status: SensorConnectionStatus
    last_reading_at: datetime | None = None


class AIModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    name: str
    version: str


class DeviceHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    device_id: str
    reported_at: datetime
    status: DeviceStatus
    software_version: str
    ai_models: list[AIModelInfo] = Field(default_factory=list)
    cpu_pct: float | None = Field(default=None, ge=0, le=100)
    memory_pct: float | None = Field(default=None, ge=0, le=100)
    storage_pct: float | None = Field(default=None, ge=0, le=100)
    cameras: list[CameraStatus] = Field(default_factory=list)
    sensors: list[SensorStatus] = Field(default_factory=list)
    outbox_pending: int = Field(default=0, ge=0)
